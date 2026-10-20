#!/usr/bin/env python3
"""Sprint Intelligence semantic review plans, epic selection and publication gates.

No Jira network access. Semantic second-pass labels/epic assessments and sharpwriter
receipts are supplied by the Quick agent after independently inspecting source evidence.
This utility checks their coverage, consistency and deterministic inclusion rules.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys

import sprint_pipeline as sp

SUBSTANTIVE = {"product_feature", "product_enhancement", "bug_fix", "platform_enablement", "engineering_improvement"}
ROUTINE = {"operational_support", "administrative", "maintenance"}
SCOPE = {"customer", "internal", "operations", "unknown"}
STATES = {"delivered_verified", "progress_verified", "blocked", "unverified", "none"}
MATERIALITY = {"high", "medium", "low", "unknown"}
RISKS = {"critical", "high", "medium", "low", "none", "unknown"}
REVIEW_RESULTS = {"agree", "corrected", "insufficient_evidence"}
CHECKS = ("factual_accuracy", "evidence_attribution", "no_unsupported_value_claims",
          "highlight_relevance", "materiality_and_risks", "clarity_and_concision", "coverage_and_uncertainty")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, data: dict) -> None:
    sp.write_json(path, data)


def evidence_usable(items: object, start: dt.datetime, end: dt.datetime, dated: bool = False) -> bool:
    """Structural evidence precheck only; truth must be checked by independent reviewer."""
    if not isinstance(items, list):
        return False
    for e in items:
        if not isinstance(e, dict) or not e.get("fact") or not (e.get("url") or e.get("ref")):
            continue
        if dated:
            try:
                at = sp.parse_date(e.get("at"))
            except ValueError:
                continue
            if at is None or not start <= at <= end:
                continue
        return True
    return False


def evidence_points_to_issue(items: object, key: str) -> bool:
    """Require issue identity, not merely an arbitrary valid URL."""
    if not isinstance(items, list):
        return False
    return any(isinstance(e, dict) and (
        e.get("issue_key") == key or e.get("ref") == key or
        isinstance(e.get("url"), str) and e["url"].split("?", 1)[0].rstrip("/").endswith("/"+key)
    ) for e in items)


def make_plan(snapshot: dict, issues: list[dict], labels: list[dict], routine_fraction: float = 0.25) -> dict:
    bykey = sp.indexes(issues)
    lm = sp.check_classifications(labels, bykey)
    start, end = sp.window(snapshot)
    buckets: dict[str, list[str]] = collections.defaultdict(list)
    roots = [x for x in issues if not (sp.is_epic(x) or sp.is_subtask(x))]
    for issue in sorted(roots, key=lambda z: z["key"]):
        key = issue["key"]
        c = lm.get(key)
        if c is None:
            buckets["missing_classification"].append(key)
            continue
        if c["work_type"] in SUBSTANTIVE or c["outcome"] in ("delivered_verified", "blocked") or c.get("automation_change"):
            buckets["mandatory_material"].append(key)
        elif (c["confidence"] == "low" or c["work_type"] == "unknown" or c["outcome"] == "unknown"
              or (c["outcome"] == "no_material_change" and not issue.get("changelog_complete"))):
            buckets["mandatory_ambiguous"].append(key)
        elif c["work_type"] == "incident":
            buckets["mandatory_incident"].append(key)
        else:
            buckets["routine_pool"].append(key)
    sampled = []
    for key in buckets.get("routine_pool", []):
        # Stable hash-based pseudorandom sample across reruns, immune to ticket sort order.
        h = int(hashlib.sha256((str(snapshot.get("sprint", {}).get("id")) + ":" + key).encode()).hexdigest(), 16)
        sampled.append((h, key))
    sampled.sort()
    n = min(len(sampled), max(3, int(len(sampled) * routine_fraction + 0.999999))) if sampled else 0
    selected = sorted(set(buckets.get("mandatory_material", []) + buckets.get("mandatory_ambiguous", [])
                          + buckets.get("mandatory_incident", []) + buckets.get("missing_classification", [])
                          + [key for _, key in sampled[:n]]))
    reasons = {}
    for bucket, keys in buckets.items():
        for key in keys:
            if key in selected and bucket != "routine_pool":
                reasons[key] = bucket
    for _, key in sampled[:n]:
        reasons[key] = "routine_stratified_sample"
    return {
        "source_sha256": sp.fingerprint({"snapshot": snapshot, "issues": issues, "classifications": labels}),
        "schema_version": "2.0", "review_type": "independent_second_pass",
        "source_sprint": snapshot.get("sprint", {}).get("id"),
        "reviewed_window": [start.isoformat(), end.isoformat()],
        "root_issues_total": len(roots), "review_issue_keys": selected,
        "review_reasons": reasons, "mandatory_keys": sorted(k for k in selected if reasons[k] != "routine_stratified_sample"),
        "routine_pool_size": len(buckets.get("routine_pool", [])), "routine_sample_size": n,
        "sampling_method": "sha256(sprint_id:issue_key), stable 25%-minimum-3 sample of nonmandatory roots",
        "accuracy_warning": "Agreement on a reviewed sample is not measured accuracy without independently verified ground truth."
    }


def audit_reviews(snapshot: dict, issues: list[dict], labels: list[dict], plan: dict, reviews: list[dict]) -> dict:
    bykey = sp.indexes(issues)
    lm = sp.check_classifications(labels, bykey)
    start, end = sp.window(snapshot)
    canonical = make_plan(snapshot, issues, labels)
    expected = set(canonical["review_issue_keys"])
    found, problems = {}, []
    if plan != canonical:
        problems.append("review plan differs from recomputed immutable input plan; rerun review-plan")
    for row in reviews:
        key = row.get("key")
        if key in found:
            problems.append(f"duplicate reviewer result {key}")
            continue
        if key not in expected:
            problems.append(f"unexpected reviewer result {key}")
            continue
        found[key] = row
        if row.get("source_sha256") != canonical["source_sha256"]:
            problems.append(f"{key}: reviewer result not bound to current source_sha256")
        if row.get("verdict") not in REVIEW_RESULTS:
            problems.append(f"{key}: bad reviewer verdict")
        if row.get("source_checked") is not True:
            problems.append(f"{key}: source not independently checked")
        if not row.get("review_note"):
            problems.append(f"{key}: missing reviewer explanation")
        if not evidence_usable(row.get("evidence_checked"), start, end, dated=False):
            problems.append(f"{key}: reviewer needs a traceable evidence reference")
        if not evidence_points_to_issue(row.get("evidence_checked"), key):
            problems.append(f"{key}: reviewer evidence does not identify this issue")
        reviewed = row.get("reviewed_labels") or {}
        primary = lm.get(key) or {}
        for field in ("work_type", "execution_mode", "outcome"):
            if reviewed.get(field) not in {"work_type":sp.WORK_TYPES, "execution_mode":sp.EXECUTION_MODES,
                                           "outcome":sp.OUTCOMES}[field]:
                problems.append(f"{key}: independent reviewer missing/invalid {field}")
            if primary.get(field) != reviewed.get(field):
                problems.append(f"{key}: primary/reviewer {field} disagreement ({primary.get(field)} vs {reviewed.get(field)})")
        if row.get("verdict") != "agree":
            problems.append(f"{key}: reviewer did not approve classification ({row.get('verdict')})")
        if primary.get("outcome") == "delivered_verified" and not evidence_usable(primary.get("evidence"), start, end, dated=True):
            problems.append(f"{key}: delivery verification lacks dated in-window source evidence")
    missing = sorted(expected - set(found))
    problems += [f"{key}: missing mandatory second-pass review" for key in missing]
    for key, c in lm.items():
        if c["outcome"] == "delivered_verified" and key not in expected and not sp.is_subtask(bykey[key]) and not sp.is_epic(bykey[key]):
            problems.append(f"{key}: verified root delivery was not in review plan")
    checked = len(expected & set(found))
    agrees = sum(found[k].get("verdict") == "agree" and all(
        found[k].get("reviewed_labels", {}).get(field) == lm.get(k, {}).get(field)
        for field in ("work_type", "execution_mode", "outcome")) for k in expected & set(found))
    return {"pass": not problems, "planned":len(expected), "reviewed":checked, "agreed":agrees,
            "agreement_on_reviewed_fraction":round(agrees/checked, 4) if checked else None,
            "problems":problems,
            "interpretation":"Second-review agreement is not a calibrated accuracy statistic; manual gold labels are needed for accuracy."}



def gold_audit(issues: list[dict], labels: list[dict], gold: list[dict]) -> dict:
    """Compare against externally verified reference labels, NOT self-generated model labels.

    Accuracy on a selected reference set is not a population-wide estimate unless the
    gold set was sampled representatively; publish counts and selection caveat.
    """
    bykey=sp.indexes(issues)
    lm=sp.check_classifications(labels,bykey)
    bad=[]
    scores={field: {"matched":0,"total":0,"mismatch_keys":[],"confusion":collections.Counter()}
            for field in ("work_type","execution_mode","outcome")}
    seen=set()
    for row in gold:
        key=row.get("key")
        if key in seen:
            bad.append(f"duplicate gold key {key}")
            continue
        seen.add(key)
        if key not in bykey or sp.is_subtask(bykey[key]) or sp.is_epic(bykey[key]):
            bad.append(f"gold label key not a root issue: {key}")
            continue
        if not row.get("human_verified") or not row.get("reviewer_id") or not row.get("source_ref"):
            bad.append(f"{key}: reference gold must have human_verified, reviewer_id and source_ref")
            continue
        for field in scores:
            accepted={"work_type":sp.WORK_TYPES,"execution_mode":sp.EXECUTION_MODES,"outcome":sp.OUTCOMES}[field]
            expected=row.get(field)
            if expected not in accepted:
                bad.append(f"{key}: missing/invalid gold {field}")
                continue
            predicted=(lm.get(key) or {}).get(field) or "<missing>"
            s=scores[field]
            s["total"]+=1
            s["confusion"][(expected,predicted)] += 1
            if predicted==expected:s["matched"]+=1
            else:s["mismatch_keys"].append(key)
    results={}
    for field,x in scores.items():
        results[field]={"matches":x["matched"],"n":x["total"],
                        "accuracy_on_gold_fraction":round(x["matched"]/x["total"],4) if x["total"] else None,
                        "mismatch_keys":x["mismatch_keys"],
                        "confusion":[{"gold":k[0],"predicted":k[1],"count":v} for k,v in sorted(x["confusion"].items())]}
    mismatches=sorted({key for x in scores.values() for key in x["mismatch_keys"]})
    return {"pass":not bad and not mismatches,"n_reference_issues":len(seen),"axes":results,
            "problems":bad+[f"reference-gold disagreement: {key}" for key in mismatches],
            "scope_note":"Accuracy is measured only against externally human-verified reference labels; if selected purposively it is not population accuracy."}


def evaluate_epics(snapshot: dict, issues: list[dict], labels: list[dict], assessments: list[dict],
                   max_highlights: int = 5, contexts: dict[str, dict] | None = None,
                   source_sha256: str | None = None) -> dict:
    start, end = sp.window(snapshot)
    bykey = sp.indexes(issues)
    lm = sp.check_classifications(labels, bykey)
    roots = collections.defaultdict(list)
    epics = set()
    for issue in issues:
        epic = sp.root_epic(issue, bykey)
        epics.add(epic)
        if not (sp.is_epic(issue) or sp.is_subtask(issue)):
            roots[epic].append((issue, lm.get(issue["key"])))
    byepic, problems = {}, []
    for a in assessments:
        key = a.get("epic_key")
        if key not in epics:
            problems.append(f"assessment epic not in export: {key}")
            continue
        if key in byepic:
            problems.append(f"duplicate epic assessment: {key}")
            continue
        byepic[key] = a
    decisions = []
    for epic in sorted(epics):
        items = roots[epic]
        a = byepic.get(epic)
        kinds = {c["work_type"] for _, c in items if c}
        all_routine = bool(items) and bool(kinds) and kinds.issubset(ROUTINE) and all(c for _, c in items)
        substantive = any(c and c["work_type"] in SUBSTANTIVE for _, c in items)
        incident_only = bool(kinds) and kinds.issubset(ROUTINE | {"incident"}) and not substantive
        entry = {"epic_key":epic, "epic_url":bykey.get(epic, {}).get("url"),
                 "work_types":sorted(kinds), "root_issue_count":len(items), "classification_mode":"all_routine" if all_routine else "mixed_or_substantive",
                 "selected":False,"section":"epic_appendix","reason":None}
        if all_routine:
            entry.update(section="operational_workload",reason="manual_or_routine_operations_only")
            decisions.append(entry)
            continue
        if incident_only:
            entry.update(section="reliability_and_incidents",reason="incident_or_routine_only")
            decisions.append(entry)
            continue
        if epic == sp.NO_EPIC:
            entry.update(reason="unassigned_items_are_not_a_named_epic")
            decisions.append(entry)
            continue
        if not substantive:
            entry.update(reason="no_substantive_engineering_or_product_work")
            decisions.append(entry)
            continue
        epic_context = (contexts or {}).get(epic)
        entry["context_status"] = (epic_context or {}).get("context_status", "unavailable")
        if entry["context_status"] != "complete":
            problems.append(f"{epic}: substantive epic context incomplete; re-fetch goal/acceptance/links before assessing highlights")
            entry.update(reason="epic_context_incomplete")
            decisions.append(entry)
            continue
        if epic_context.get("reporting_scope") == "out_of_scope" or epic_context.get("owning_team") == "DWH":
            entry.update(section="external_dependency", reason="DWH/external epic cannot be a Reporting highlight")
            decisions.append(entry)
            continue
        if not a:
            problems.append(f"{epic}: material epic needs a sourced assessment")
            entry["reason"] = "missing_epic_assessment"
            decisions.append(entry)
            continue
        if a.get("context_sha256") != sp.fingerprint(epic_context):
            problems.append(f"{epic}: epic assessment is not bound to current context hash")
        if source_sha256 is not None and a.get("source_sha256") != source_sha256:
            problems.append(f"{epic}: epic assessment is not bound to current review source hash")
        for field, values in (("initiative_scope",SCOPE),("milestone_state",STATES),
                              ("materiality",MATERIALITY),("risk_level",RISKS)):
            if a.get(field) not in values:
                problems.append(f"{epic}: invalid {field}={a.get(field)!r}")
        if a.get("source_checked") is not True:
            problems.append(f"{epic}: epic goal/milestone not independently checked")
        if not a.get("goal") or not a.get("milestone"):
            problems.append(f"{epic}: missing goal or sprint milestone description")
        in_window = evidence_usable(a.get("evidence"),start,end,dated=True)
        # A high-impact milestone must be supported by both review and original issue evidence.
        verified_issues = [x["key"] for x,c in items if c and c["work_type"] in SUBSTANTIVE
                           and c["outcome"] == "delivered_verified" and evidence_usable(c.get("evidence"),start,end,dated=True)]
        progress_issues = [x["key"] for x,c in items if c and c["work_type"] in SUBSTANTIVE
                           and c["outcome"] in ("in_progress", "blocked") and evidence_usable(c.get("evidence"),start,end,dated=True)]
        state=a.get("milestone_state")
        if state == "delivered_verified" and not verified_issues:
            problems.append(f"{epic}: epic claims delivered milestone without verified substantive root issue")
        if state in ("progress_verified", "blocked") and not (progress_issues or verified_issues):
            problems.append(f"{epic}: epic claims material movement/risk without supporting root evidence")
        if state in ("delivered_verified", "progress_verified", "blocked") and not in_window:
            problems.append(f"{epic}: milestone missing dated in-window evidence")
        entry.update(scope=a.get("initiative_scope"),goal=a.get("goal"),milestone=a.get("milestone"),
                     milestone_state=state,materiality=a.get("materiality"),risk_level=a.get("risk_level"),
                     evidence=(a.get("evidence") or [])[:4],verified_issue_keys=verified_issues,
                     progress_issue_keys=progress_issues)
        if a.get("initiative_scope") not in ("customer", "internal"):
            entry.update(reason="not_customer_or_internal_initiative")
        elif a.get("materiality") not in ("high", "medium"):
            entry.update(reason="insufficient_materiality_for_top_highlight")
        elif state not in ("delivered_verified", "progress_verified", "blocked"):
            entry.update(reason="milestone_not_evidence_verified")
        elif not in_window:
            entry.update(reason="milestone_evidence_not_in_sprint")
        elif state == "delivered_verified" and not verified_issues:
            entry.update(reason="delivery_not_correlated_with_root_issue")
        elif state in ("progress_verified", "blocked") and not (progress_issues or verified_issues):
            entry.update(reason="progress_not_correlated_with_root_issue")
        else:
            entry.update(section="highlight_candidate",reason="eligible_material_milestone")
        decisions.append(entry)
    candidates = [d for d in decisions if d["section"] == "highlight_candidate"]
    scope_order={"customer":0,"internal":1}
    material_order={"high":0,"medium":1}
    state_order={"delivered_verified":0,"blocked":1,"progress_verified":2}
    # Evidence-backed severity outranks audience; customer wins genuine ties.
    candidates.sort(key=lambda d:(material_order[d["materiality"]],
                                  state_order[d["milestone_state"]],scope_order[d["scope"]],d["epic_key"]))
    for position, e in enumerate(candidates):
        if position < max_highlights:
            e["selected"] = True
            e["section"] = "executive_highlights"
        else:
            e["section"] = "other_material_initiatives"
            e["reason"] = "valid_but_exceeds_highlight_cap"
    return {"pass": not problems,"max_highlights":max_highlights,
            "selected_epic_keys":[x["epic_key"] for x in candidates[:max_highlights]],
            "decisions":decisions,"problems":problems,
            "rule":"Materiality, verified milestone state, then customer-vs-internal tie break; no issue-count scoring."}



def validate_fan_in(snapshot: dict, issues: list[dict], epic_context: list[dict],
                    labels: list[dict], manifest: dict, packets: list[dict],
                    worker_results: list[dict]) -> dict:
    """Recompute worker provenance from the frozen source before semantic assessment.

    This prevents a caller from bypassing merge-packets by substituting arbitrary
    classifications and a matching second-pass review plan.
    """
    source_digest = sp.fingerprint({"snapshot": snapshot, "issues": issues, "epics": epic_context})
    run_id = snapshot.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("fan-in requires a nonempty snapshot.run_id")
    if not isinstance(manifest, dict) or manifest.get("run_id") != run_id \
       or manifest.get("sprint_id") != snapshot.get("sprint", {}).get("id") \
       or manifest.get("source_sha256") != source_digest:
        raise ValueError("source_manifest does not match the current immutable Jira/epic source")
    if not isinstance(packets, list) or not packets:
        raise ValueError("fan-in requires at least one prepared packet")
    source_keys = set(sp.indexes(issues))
    packet_keys = [key for packet in packets for key in packet.get("source_issue_keys", [])]
    if len(packet_keys) != len(set(packet_keys)) or set(packet_keys) != source_keys:
        raise ValueError("prepared packets do not cover the exact current sprint key universe")
    for packet in packets:
        if packet.get("source_manifest_sha256") != source_digest or packet.get("run_id") != run_id:
            raise ValueError(f"{packet.get('packet_id')}: packet from a different frozen run")
    canonical, merged_coverage = sp.merge_packet_results(packets, worker_results)
    if canonical != sorted(labels, key=lambda row: row.get("key", "")):
        raise ValueError("classifications differ from verified worker fan-in; rerun merge-packets")
    return {"pass": True, "source_manifest_sha256": source_digest,
            "packet_count": merged_coverage["packets_merged"],
            "issue_count": merged_coverage["issues_covered"],
            "packet_results_sha256": sp.fingerprint(worker_results),
            "classifications_sha256": sp.fingerprint(canonical)}


def assess(args: argparse.Namespace) -> None:
    snapshot=sp.read_json(args.snapshot)
    issues=sp.read_jsonl(args.issues)
    labels=sp.read_jsonl(args.classifications)
    epic_rows=sp.read_jsonl(args.epics)
    fan_in=validate_fan_in(
        snapshot, issues, epic_rows, labels,
        sp.read_json(args.source_manifest),
        sp.read_jsonl(args.packets),
        sp.read_jsonl(args.packet_results))
    plan=sp.read_json(args.plan)
    reviews=sp.read_jsonl(args.reviews)
    epics=sp.read_jsonl(args.epic_assessments)
    cov=sp.coverage(snapshot,issues,labels)
    review=audit_reviews(snapshot,issues,labels,plan,reviews)
    bykey = sp.indexes(issues)
    expected_epics = {sp.root_epic(i, bykey) for i in issues} - {sp.NO_EPIC}
    contexts = sp.epic_context_index(epic_rows, expected_epics)
    selection=evaluate_epics(snapshot,issues,labels,epics,args.max_highlights,contexts,
                             source_sha256=sp.fingerprint({"snapshot":snapshot,"issues":issues,"classifications":labels}))
    gold=gold_audit(issues,labels,sp.read_jsonl(args.gold)) if args.gold else None
    issues_out=[]
    if not cov["coverage_complete"]: issues_out.append("incomplete Jira issue extraction")
    if not cov["reporting_ownership"]["pass"]:
        issues_out.append("Reporting ownership routing could not be validated")
    if cov["unclassified_issue_keys"]: issues_out.append("unclassified issues in Jira export")
    if not review["pass"]: issues_out.append("independent classification review did not pass")
    if not selection["pass"]: issues_out.append("epic selection checks did not pass")
    if gold and not gold["pass"]: issues_out.append("human reference gold check did not pass")
    gate={"pass":not issues_out, "blockers":issues_out,
          "epic_context_sha256":sp.fingerprint(epic_rows), "worker_fan_in":fan_in,
          "source_sha256": sp.fingerprint({"snapshot":snapshot,"issues":issues,"classifications":labels}),
          "sprint_id": snapshot.get("sprint",{}).get("publication_id", snapshot.get("sprint",{}).get("id")), "coverage":cov,
          "classification_review":review,"reference_gold_accuracy":gold,
          "highlight_selection":selection}
    out=Path(args.out)
    write(out/"quality.json",gate)
    write(out/"highlight_selection.json",selection)
    print(f"Quality gate: {'PASS' if gate['pass'] else 'FAIL'}; selected {len(selection['selected_epic_keys'])} highlights")
    if issues_out:
        for x in issues_out: print("BLOCKER: "+x,file=sys.stderr)
        raise SystemExit(3)


def plan(args: argparse.Namespace) -> None:
    obj=make_plan(sp.read_json(args.snapshot),sp.read_jsonl(args.issues),sp.read_jsonl(args.classifications))
    write(Path(args.out)/"classification_review_plan.json",obj)
    print(f"Review plan: {len(obj['review_issue_keys'])}/{obj['root_issues_total']} root issues")


def publication_check(quality: dict, selection: dict, receipt: dict, manifest: dict,
                      report: Path, payload: dict) -> dict:
    """Structural integrity checks. Cannot authenticate an external skill invocation."""
    from pages.validate_report import validate
    problems = []
    if quality.get("pass") is not True or (quality.get("classification_review") or {}).get("pass") is not True \
       or (quality.get("highlight_selection") or {}).get("pass") is not True \
       or (quality.get("coverage") or {}).get("coverage_complete") is not True \
       or (quality.get("worker_fan_in") or {}).get("pass") is not True:
        problems.append("upstream classification/selection/coverage gates not passed")
    approved = (quality.get("highlight_selection") or {}).get("selected_epic_keys")
    chosen = selection.get("selected_epic_keys")
    if not isinstance(approved, list) or chosen != approved or selection != quality.get("highlight_selection"):
        problems.append("selection differs from quality-approved ordered highlights/assessment")
    if not isinstance(chosen, list):
        chosen = []
    if manifest.get("highlighted_epic_keys") != chosen:
        problems.append("report manifest differs from exact approved highlight order")
    try:
        sha = digest(report)
        report_text = report.read_text(encoding="utf-8")
    except OSError as e:
        sha, report_text = "", ""
        problems.append(f"cannot read final report: {e}")
    if manifest.get("report_sha256") != sha:
        problems.append("report modified after manifest")
    if str(receipt.get("skill_name") or "").casefold() != "sharpwriter":
        problems.append("sharpwriter skill not used")
    if not receipt.get("review_reference") or not receipt.get("checked_at"):
        problems.append("missing sharpwriter invocation reference/timestamp")
    if receipt.get("status") != "pass" or receipt.get("report_sha256") != sha:
        problems.append("sharpwriter pass/hash missing or stale")
    # The actual sharpwriter result must cover the exact final text AND compact payload.
    for name, digest_value in (
        ("approved_payload_sha256", sp.fingerprint(payload)),
        ("quality_sha256", sp.fingerprint(quality)),
        ("selection_sha256", sp.fingerprint(selection)),
        ("source_sha256", quality.get("source_sha256")),
    ):
        if receipt.get(name) != digest_value or not digest_value:
            problems.append(f"sharpwriter receipt missing/stale {name}")
    for check in CHECKS:
        if (receipt.get("checks") or {}).get(check) is not True:
            problems.append(f"sharpwriter check not passed: {check}")
    if receipt.get("critical_issues") != 0 or receipt.get("major_issues") != 0:
        problems.append("sharpwriter unresolved issues")
    import re
    markers = re.findall(r"<!--\s*HIGHLIGHT_EPIC:([A-Za-z][A-Za-z0-9_]*-\d+)\s*-->", report_text)
    if markers != chosen:
        problems.append("executive report markers differ from approved highlight order")
    try:
        validate(payload)
    except (ValueError, TypeError, KeyError) as e:
        problems.append(f"invalid compact publication payload: {e}")
    ranks = sorted((e.get("highlight_rank"), e.get("jira_key")) for e in payload.get("epics", [])
                   if isinstance(e, dict) and e.get("highlight_rank") is not None)
    payload_keys = [key for _,key in ranks]
    if payload_keys != chosen:
        problems.append("payload ranked highlights differ from approved highlight order")
    if str(payload.get("sprint",{}).get("id")) != str(quality.get("sprint_id")):
        problems.append("payload sprint differs from quality sprint")
    if not quality.get("source_sha256") or not quality.get("epic_context_sha256"):
        problems.append("quality lacks source or epic context fingerprint")
    return {"pass":not problems,"report_sha256":sha,
            "approved_payload_sha256":sp.fingerprint(payload),
            "quality_sha256":sp.fingerprint(quality),
            "selection_sha256":sp.fingerprint(selection),
            "source_sha256":quality.get("source_sha256"),
            "sprint_id":quality.get("sprint_id"),
            "selected_epics":chosen,
            "sharpwriter_receipt_sha256":sp.fingerprint(receipt),
            "sharpwriter_receipt_verified": receipt.get("status") == "pass" and
                receipt.get("report_sha256") == sha and
                receipt.get("approved_payload_sha256") == sp.fingerprint(payload) and
                receipt.get("quality_sha256") == sp.fingerprint(quality) and
                receipt.get("selection_sha256") == sp.fingerprint(selection) and
                receipt.get("source_sha256") == quality.get("source_sha256") and
                all((receipt.get("checks") or {}).get(c) is True for c in CHECKS),
            "problems":problems,
            "warning":"Receipt consistency is checked; external invocation authenticity requires trusted Quick execution provenance."}


def publish(args: argparse.Namespace) -> None:
    quality=sp.read_json(args.quality)
    selection=sp.read_json(args.selection)
    receipt=sp.read_json(args.sharpwriter_receipt)
    manifest=sp.read_json(args.manifest)
    payload=sp.read_json(args.payload)
    result=publication_check(quality,selection,receipt,manifest,Path(args.report),payload)
    write(Path(args.out)/"publication_gate.json",result)
    print(f"Publication gate: {'PASS' if result['pass'] else 'FAIL'}")
    if not result['pass']:
        for problem in result['problems']:
            print('BLOCKER: '+problem,file=sys.stderr)
        raise SystemExit(4)


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="cmd",required=True)
    pp=sub.add_parser("review-plan",help="Select mandatory material and sampled routine issues for independent review")
    for x in (pp,):
        x.add_argument("--snapshot",required=True); x.add_argument("--issues",required=True)
        x.add_argument("--classifications",required=True); x.add_argument("--out",required=True)
    pp.set_defaults(fn=plan)
    aa=sub.add_parser("assess",help="Audit second-pass classification and select customer/internal epic highlights")
    for arg in ("snapshot","issues","epics","classifications","source-manifest","packets","packet-results","plan","reviews","epic-assessments","out"):
        aa.add_argument("--"+arg,required=True)
    aa.add_argument("--max-highlights",type=int,default=5)
    aa.add_argument("--gold",help="Optional independently human-verified root issue reference labels (JSONL)")
    aa.set_defaults(fn=assess)
    pub=sub.add_parser("publish",help="Require passed sharpwriter receipt tied to current report hash")
    for arg in ("quality","selection","report","sharpwriter-receipt","manifest","payload","out"):
        pub.add_argument("--"+arg,required=True)
    pub.set_defaults(fn=publish)
    args=p.parse_args()
    try: args.fn(args)
    except (ValueError,OSError) as e:
        print('ERROR: '+str(e),file=sys.stderr); raise SystemExit(2)

if __name__=="__main__":
    main()
