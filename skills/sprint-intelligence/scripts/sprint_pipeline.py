#!/usr/bin/env python3
"""Local, read-only Sprint Intelligence preprocessing / aggregation.

No network access; no external libraries; all Jira API responses must be normalized
by the MCP agent before invoking this script. See references/schema.md.
"""
from __future__ import annotations

import argparse
import hashlib
import collections
import datetime as dt
import json
import pathlib
import re
import sys
from typing import Any

NO_EPIC = "__NO_EPIC__"
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]+-[0-9]+$")
WORK_TYPES = {"product_feature", "product_enhancement", "bug_fix", "incident",
              "operational_support", "maintenance", "platform_enablement", "engineering_improvement",
              "discovery", "administrative", "unknown"}
EXECUTION_MODES = {"manual", "scripted_automation", "ai_assisted", "ai_automated", "mixed", "unknown"}
OUTCOMES = {"delivered_verified", "completed_unverified", "in_progress", "blocked",
            "no_material_change", "unknown"}
CONFIDENCES = {"high", "medium", "low"}
AUTOMATION_STAGES = {"proposed", "piloted", "in_use", "measured"}
AUTOMATION_TECH = {"rules_script", "ai", "mixed", "unknown"}


def fingerprint(value: Any) -> str:
    """Stable content digest; identifiers are not proof of independent review."""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def packet_digest(packet: dict) -> str:
    return fingerprint({k: v for k, v in packet.items() if k != 'packet_sha256'})


def fail(message: str) -> None:
    raise ValueError(message)


def read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        x = json.load(f)
    if not isinstance(x, dict):
        fail(f"{path} must contain an object")
    return x


def read_jsonl(path: str) -> list[dict]:
    rows: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as e:
                fail(f"{path}:{i}: invalid JSON: {e}")
            if not isinstance(value, dict):
                fail(f"{path}:{i}: expected JSON object")
            rows.append(value)
    return rows


def write_json(path: pathlib.Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def write_jsonl(path: pathlib.Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def parse_date(s: Any) -> dt.datetime | None:
    if not s or not isinstance(s, str):
        return None
    try:
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if t.tzinfo is None:
            fail(f"Timestamp has no timezone: {s}")
        return t
    except ValueError as e:
        fail(f"Bad timestamp {s!r}: {e}")


def window(snapshot: dict) -> tuple[dt.datetime, dt.datetime]:
    sprint = snapshot.get("sprint") or {}
    a = parse_date(sprint.get("start"))
    b = parse_date(sprint.get("end"))
    asof = parse_date(snapshot.get("as_of"))
    if a is None or asof is None:
        fail("snapshot.sprint.start and snapshot.as_of are required timezone-aware ISO timestamps")
    hi = min(b, asof) if b is not None else asof
    if a > hi:
        fail("Invalid sprint window: start later than effective end")
    return a, hi


def valid_key(key: Any) -> bool:
    return isinstance(key, str) and bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*-\d+", key))


def indexes(issues: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i, issue in enumerate(issues, 1):
        key = issue.get("key")
        if not valid_key(key):
            fail(f"issue record {i} requires a valid Jira key, got {key!r}")
        if key in out:
            fail(f"duplicate issue key: {key}; deduplicate during extraction, not in analysis")
        out[key] = issue
    return out


def is_epic(issue: dict) -> bool:
    return str(issue.get("issue_type") or "").casefold() == "epic"


def is_subtask(issue: dict) -> bool:
    return bool(issue.get("is_subtask")) or str(issue.get("issue_type") or "").lower().replace("-", "").replace(" ", "") in ("subtask", "subtarea")


def root_epic(issue: dict, bykey: dict[str, dict]) -> str:
    if is_epic(issue):
        return issue["key"]
    if isinstance(issue.get("epic_key"), str) and issue["epic_key"].strip():
        return issue["epic_key"].strip()
    seen = {issue["key"]}
    parent = issue.get("parent_key")
    for _ in range(15):
        if not parent:
            return NO_EPIC
        if parent in seen:
            fail(f"{issue['key']}: cyclic parent hierarchy at {parent}")
        if parent not in bykey:
            fail(f"{issue['key']}: unresolved external parent {parent}; fetch parent and resolve epic_key before prepare")
        seen.add(parent)
        p = bykey[parent]
        if is_epic(p):
            return p["key"]
        if p.get("epic_key"):
            return p["epic_key"]
        parent = p.get("parent_key")
    return NO_EPIC


def transitions(issue: dict, start: dt.datetime, end: dt.datetime) -> list[dict]:
    out = []
    for entry in issue.get("changelog") or []:
        if not isinstance(entry, dict):
            continue
        when = parse_date(entry.get("at"))
        if when and start <= when <= end:
            out.append({k: entry.get(k) for k in ("at", "field", "from", "to", "url")})
    return sorted(out, key=lambda x: x.get("at") or "")


def status_events(events: list[dict]) -> list[dict]:
    return [x for x in events if str(x.get("field") or "").lower() in ("status", "statuscategory")]


def safe_cut(x: Any, size: int) -> str:
    text = x if isinstance(x, str) else ""
    return text[:size] + ("… [truncated]" if len(text) > size else "")


def issue_comment_coverage(issue: dict) -> dict:
    """Validate that Jira comments were read in full, including pagination.

    Missing comments are not the same as a confirmed zero-comment issue.
    """
    key = issue.get("key", "<unknown>")
    problems = []
    comments = issue.get("comments")
    complete = issue.get("comments_complete") is True
    count = issue.get("comments_total")
    pages = issue.get("comments_pages")
    if not isinstance(comments, list):
        problems.append("comments must be an array (empty only after a verified fetch)")
        comments = []
    if type(count) is not int or count < 0:
        problems.append("comments_total must be a nonnegative integer from the provider")
    if type(pages) is not int or pages < 1:
        problems.append("comments_pages must record at least one confirmed read/page")
    if issue.get("comments_complete") not in (True, False):
        problems.append("comments_complete must be explicitly true or false")
    if type(count) is int and count != len(comments):
        problems.append(f"provider reported {count} comments, normalized {len(comments)}")
    seen = set()
    for index, comment in enumerate(comments):
        if not isinstance(comment, dict):
            problems.append(f"comment {index} must be an object")
            continue
        comment_id = comment.get("id")
        if not isinstance(comment_id, (str, int)) or isinstance(comment_id, bool) or not str(comment_id).strip():
            problems.append(f"comment {index} missing stable Jira comment id")
        elif str(comment_id) in seen:
            problems.append(f"duplicate comment id {comment_id}")
        else:
            seen.add(str(comment_id))
        try:
            if parse_date(comment.get("created")) is None:
                problems.append(f"comment {index} missing created timestamp")
            if comment.get("updated") is not None:
                updated = parse_date(comment["updated"])
                created = parse_date(comment.get("created"))
                if created and updated and updated < created:
                    problems.append(f"comment {index} updated before created")
        except ValueError as e:
            problems.append(f"comment {index} invalid timestamp: {e}")
        body = comment.get("body")
        if not isinstance(body, str):
            problems.append(f"comment {index} body must be normalized as text, including redacted/empty text")
        url = comment.get("url")
        if not isinstance(url, str) or not url.startswith("https://") or f"/browse/{key}" not in url:
            problems.append(f"comment {index} requires an issue-specific source URL")
    if not complete:
        problems.append("comments_complete=false or unavailable; final publication requires full pagination")
    return {"pass": not problems, "key": key, "total": count,
            "retrieved": len(comments), "pages": pages,
            "complete": complete, "problems": problems}


def feature(issue: dict, epic: str, start: dt.datetime, end: dt.datetime) -> dict:
    events = transitions(issue, start, end)
    comment_check = issue_comment_coverage(issue)
    comments = issue.get("comments") if isinstance(issue.get("comments"), list) else []
    ordered_comments = sorted(
        (c for c in comments if isinstance(c, dict) and isinstance(c.get("created"), str)),
        key=lambda c: (parse_date(c["created"]), str(c.get("id", ""))))
    in_window = [c for c in ordered_comments if start <= parse_date(c["created"]) <= end]
    prior = [c for c in ordered_comments if parse_date(c["created"]) < start]
    def excerpt(c: dict) -> dict:
        return {"id": str(c.get("id", "")), "at": c.get("created"),
                "updated": c.get("updated"), "text": safe_cut(c.get("body"), 650),
                "url": c.get("url")}
    # These excerpts are navigation aids, not the complete evidence corpus.
    comments_window = [excerpt(c) for c in in_window[-4:]]
    comments_prior = [excerpt(c) for c in prior[-2:]]
    links = issue.get("links") or []
    if not isinstance(links, list):
        links = []
    blocker = any("block" in str(l).lower() for l in links) or "block" in str(issue.get("status", "")).lower()
    return {
        "key": issue["key"], "epic_key": epic, "root_counted": not (is_epic(issue) or is_subtask(issue)),
        "is_epic": is_epic(issue), "is_subtask": is_subtask(issue),
        "issue_type": issue.get("issue_type"), "summary": safe_cut(issue.get("summary"), 300),
        "description_excerpt": safe_cut(issue.get("description"), 1200),
        "status": issue.get("status"), "status_category": issue.get("status_category"),
        "priority": issue.get("priority"), "url": issue.get("url"),
        "created": issue.get("created"), "resolved": issue.get("resolved"),
        "status_events": status_events(events), "in_window_change_count": len(events),
        "in_window_comments": comments_window, "in_window_comment_count": len(in_window),
        "prior_context_comments": comments_prior,
        "comments_complete": comment_check["pass"], "comments_total": comment_check["total"],
        "comments_retrieved": comment_check["retrieved"],
        "link_excerpt": links[:8], "potential_blocker": blocker,
        "evidence_truncated": any(isinstance(issue.get(k), str) and len(issue[k]) > size
                                  for k, size in (("summary", 300), ("description", 1200)))
                              or any(len(str(c.get("body") or c.get("text") or "")) > 650
                                     for c in comments if isinstance(c, dict))
                              or len(in_window) > 4 or len(prior) > 2 or len(links) > 8,
        "source_counts": {"comments": len(comments), "in_window_comments": len(in_window),
                          "prior_comments": len(prior), "links": len(links)},
        "parent_key": issue.get("parent_key"),
        "changelog_available": "changelog" in issue,
        "changelog_complete": issue.get("changelog_complete"),
    }


def epic_context_index(rows: list[dict], expected: set[str]) -> dict[str, dict]:
    """Epic goal/acceptance context is outside the sprint issue-counting universe."""
    mapped: dict[str, dict] = {}
    for idx, row in enumerate(rows, 1):
        key = row.get("epic_key")
        if key == NO_EPIC or not valid_key(key):
            fail(f"epic_context record {idx}: invalid epic_key {key!r}")
        if key in mapped:
            fail(f"duplicate epic context for {key}")
        if key not in expected:
            fail(f"epic context {key} not referenced by sprint issue keys")
        if row.get("context_status") not in ("complete", "partial", "unavailable"):
            fail(f"{key}: context_status must be complete, partial or unavailable")
        if row["context_status"] == "complete":
            acceptance = row.get("acceptance_criteria")
            state = row.get("acceptance_status")
            if state not in ("present", "not_defined_at_source", "not_applicable"):
                fail(f"{key}: complete context requires acceptance_status (present/not_defined_at_source/not_applicable)")
            if state == "present" and not (isinstance(acceptance, str) and acceptance.strip()):
                fail(f"{key}: acceptance_status=present requires acceptance_criteria")
            if state != "present" and not row.get("acceptance_reason"):
                fail(f"{key}: missing acceptance criteria needs an explicit source-checked reason")
        if row["context_status"] == "unavailable":
            if not row.get("reason_missing"):
                fail(f"{key}: unavailable epic context requires reason_missing")
        else:
            if not row.get("url") or not row.get("summary"):
                fail(f"{key}: available epic context must identify Jira issue and URL")
            if not isinstance(row.get("source_refs"), list) or not row["source_refs"]:
                fail(f"{key}: available epic context needs source_refs")
            if row["context_status"] == "complete" and not (row.get("goal") or row.get("description")):
                fail(f"{key}: complete epic context needs the retrieved goal or description")
        mapped[key] = row
    missing = expected - set(mapped)
    if missing:
        fail("missing epic_context.jsonl rows for sprint epics: " + ", ".join(sorted(missing)))
    return mapped


def compact_epic_context(raw: dict, max_chars: int) -> dict:
    """Keep full source in the ephemeral epic_context file, not repeated per packet."""
    fields = ("epic_key", "context_status", "summary", "goal", "description",
              "acceptance_criteria", "acceptance_status", "acceptance_reason",
              "scope", "status", "owning_team",
              "reporting_scope", "url", "source_refs", "reason_missing")
    result = {k: raw.get(k) for k in fields if k in raw}
    truncated = []
    for field, size in (("description", 1200), ("goal", 1000),
                        ("acceptance_criteria", 1200), ("scope", 500), ("summary", 300)):
        if isinstance(result.get(field), str):
            if len(result[field]) > size:
                truncated.append(field)
            result[field] = safe_cut(result[field], size)
    if isinstance(result.get("source_refs"), list):
        if len(result["source_refs"]) > 6: truncated.append("source_refs")
        result["source_refs"] = result["source_refs"][:6]
    if len(json.dumps(result, ensure_ascii=False)) > max_chars:
        for field in ("description", "acceptance_criteria", "scope", "goal"):
            if field in result:
                if isinstance(result[field], str) and len(result[field]) > 150:
                    truncated.append(field)
                result[field] = safe_cut(result[field], 150)
        if isinstance(result.get("source_refs"), list):
            if len(result["source_refs"]) > 2: truncated.append("source_refs")
            result["source_refs"] = result["source_refs"][:2]
    if len(json.dumps(result, ensure_ascii=False)) > max_chars:
        fail(f"Epic context {raw.get('epic_key')} exceeds packet budget; reduce text, not source pointers")
    result["context_truncated_fields"] = sorted(set(truncated))
    return result


def packetize(features: list[dict], max_items: int, max_chars: int,
              contexts: dict[str, dict] | None = None,
              source_manifest_sha256: str | None = None,
              run_id: str | None = None) -> list[dict]:
    """Split by epic, bounded *including* repeated compact epic context."""
    if max_items < 1 or max_chars < 3000:
        fail("max-items must be >= 1; max-chars must be >= 3000")
    grouped: dict[str, list[dict]] = collections.defaultdict(list)
    for row in features:
        grouped[row["epic_key"]].append(row)
    packets = []
    for epic in sorted(grouped):
        raw_ctx = (contexts or {}).get(epic, {"epic_key": epic, "context_status": "unavailable",
                                                 "reason_missing": "legacy test-only packetization without epic export"})
        if epic == NO_EPIC:
            raw_ctx = {"epic_key": epic, "context_status": "not_applicable",
                       "reason_missing": "root issues have no parent epic"}
        ctx = compact_epic_context(raw_ctx, min(3500, max_chars // 3))
        base = {"epic_key": epic, "epic_context": ctx,
                "source_manifest_sha256": source_manifest_sha256, "run_id": run_id}
        batch: list[dict] = []
        seq = 1
        for row in sorted(grouped[epic], key=lambda x: x["key"]):
            item = dict(row)
            def packet_for(candidate: list[dict]) -> dict:
                packet = {"packet_id": f"{epic}__{seq:03d}", **base,
                          "source_issue_keys": [x["key"] for x in candidate], "issues": candidate}
                packet["packet_sha256"] = packet_digest(packet)
                return packet
            trial = packet_for(batch + [item])
            length = lambda value: len(json.dumps(value, ensure_ascii=False))
            if batch and (len(batch) >= max_items or length(trial) > max_chars):
                packets.append(packet_for(batch))
                seq += 1
                batch = []
            trial = packet_for(batch + [item])
            if length(trial) > max_chars:
                item["description_excerpt"] = safe_cut(item.get("description_excerpt"), 150)
                item["in_window_comments"] = []
                item["prior_context_comments"] = []
                item["link_excerpt"] = []
                item["status_events"] = item["status_events"][:4]
                item["evidence_truncated"] = True
                trial = packet_for(batch + [item])
            if length(trial) > max_chars:
                fail(f"{item['key']}: packet still exceeds budget; use direct source re-read or larger limit")
            batch.append(item)
        if batch:
            packets.append(packet_for(batch))
    return packets


def merge_packet_results(packets: list[dict], results: list[dict]) -> tuple[list[dict], dict]:
    """Fail closed on missing, duplicate, out-of-packet or changed issue identities."""
    expected = {p["packet_id"]: p for p in packets}
    if len(expected) != len(packets):
        fail("duplicate packet IDs in preparation")
    seen: dict[str, dict] = {}
    classifications: dict[str, dict] = {}
    for result in results:
        pid = result.get("packet_id")
        if pid not in expected or pid in seen:
            fail(f"unknown or duplicate packet result: {pid!r}")
        packet = expected[pid]
        if packet.get("packet_sha256") != packet_digest(packet):
            fail(f"{pid}: prepared packet bytes do not match packet fingerprint")
        if result.get("packet_sha256") != packet["packet_sha256"]:
            fail(f"{pid}: stale or unbound worker result (packet_sha256 mismatch)")
        if result.get("source_manifest_sha256") != packet.get("source_manifest_sha256"):
            fail(f"{pid}: source manifest mismatch")
        if result.get("run_id") != packet.get("run_id"):
            fail(f"{pid}: run_id mismatch")
        if result.get("epic_key") != packet["epic_key"]:
            fail(f"{pid}: result epic_key mismatch")
        rows = result.get("classifications")
        if not isinstance(rows, list):
            fail(f"{pid}: classifications must be a list")
        expected_keys = packet["source_issue_keys"]
        actual = [x.get("key") for x in rows if isinstance(x, dict)]
        if len(actual) != len(rows) or len(actual) != len(set(actual)) or sorted(actual) != sorted(expected_keys):
            fail(f"{pid}: issue keys differ from assigned packet; no omission, additions or duplicates allowed")
        for row in rows:
            if row["key"] in classifications:
                fail(f"duplicate classification across packets: {row['key']}")
            classifications[row["key"]] = row
        seen[pid] = result
    missing = set(expected) - set(seen)
    if missing:
        fail("missing worker packet results: " + ", ".join(sorted(missing)))
    ordered = [classifications[key] for key in sorted(classifications)]
    return ordered, {"packets_expected": len(expected), "packets_merged": len(seen),
                     "issues_covered": len(classifications), "all_packets_covered": True}


def scope_ownership(snapshot: dict, issues: list[dict]) -> dict:
    """Reconcile exact provider sprint keys, Reporting keys and cited exclusions.

    An asserted team field is not evidence of actual ownership. Quick must
    independently verify source_ref against the Jira issue before admission.
    """
    meta = snapshot.get("reporting_ownership") or {}
    problems: list[str] = []
    if meta.get("verified") is not True or not meta.get("rule"):
        problems.append("Reporting ownership rule is not explicitly verified")
    provider = meta.get("provider_issue_keys")
    if not isinstance(provider, list) or not provider or not all(isinstance(k,str) and KEY_RE.fullmatch(k) for k in provider) or len(set(provider)) != len(provider):
        problems.append("provider_issue_keys must be a complete unique provider-key list")
        provider = []
    legacy = meta.get("excluded_other_team_issue_keys")
    if legacy is not None:
        problems.append("legacy excluded_other_team_issue_keys is unsupported; provide per-key ownership evidence")
    records = meta.get("excluded_other_team_issues", [])
    if not isinstance(records, list):
        problems.append("excluded_other_team_issues must be a list")
        records = []
    excluded_keys: list[str] = []
    for index, item in enumerate(records):
        if not isinstance(item, dict) or set(item) != {"key", "team", "source_ref", "reason", "ownership_verified"}:
            problems.append(f"excluded_other_team_issues[{index}]: invalid evidence record")
            continue
        key = item["key"]
        team = item["team"]
        ref = item["source_ref"]
        if not isinstance(key,str) or not KEY_RE.fullmatch(key):
            problems.append(f"excluded_other_team_issues[{index}]: invalid Jira key")
            continue
        excluded_keys.append(key)
        if not isinstance(team,str) or team.strip().casefold() in ("", "reporting"):
            problems.append(f"{key}: excluded task must have a verified non-Reporting owner")
        if item["ownership_verified"] is not True or not isinstance(item["reason"],str) or not item["reason"].strip():
            problems.append(f"{key}: missing independently checked ownership reason")
        if not isinstance(ref,str) or not ref.startswith("https://") or f"/browse/{key}" not in ref:
            problems.append(f"{key}: missing source Jira issue URL for independent ownership check")
    if len(set(excluded_keys)) != len(excluded_keys):
        problems.append("duplicate excluded keys")
    unresolved = meta.get("unresolved_issue_keys", [])
    if not isinstance(unresolved,list) or any(not isinstance(k,str) for k in unresolved) or len(set(unresolved)) != len(unresolved):
        problems.append("unresolved_issue_keys must be a unique key list")
        unresolved = []
    if unresolved:
        problems.append("Jira issues with unresolved team ownership: " + ", ".join(unresolved))
    included_keys = [issue.get("key") for issue in issues]
    if len(set(included_keys)) != len(included_keys):
        problems.append("duplicate Reporting issue keys")
    if set(included_keys) & set(excluded_keys):
        problems.append("excluded issue appears in Reporting issue universe")
    for item in issues:
        if item.get("reporting_scope") != "in_scope":
            problems.append(f"{item.get('key')}: Reporting issue must have reporting_scope=in_scope")
        if item.get("delivery_team") != "Reporting":
            problems.append(f"{item.get('key')}: non-Reporting issue cannot count as Reporting")
    combined = set(included_keys) | set(excluded_keys) | set(unresolved)
    if set(provider) != combined:
        problems.append("Provider key universe differs from included + excluded + unresolved keys")
    if set(provider) & set(unresolved) != set(unresolved):
        problems.append("unresolved issue absent from provider key universe")
    expected = meta.get("provider_member_count")
    if type(expected) is not int or expected != len(provider):
        problems.append("provider_member_count must equal exact provider_issue_keys length")
    return {"pass": not problems, "problems": problems,
            "included_reporting_issues":len(included_keys),
            "excluded_other_team_issues":len(excluded_keys),
            "provider_issue_keys": sorted(provider),
            "verified": meta.get("verified") is True}

def coverage(snapshot: dict, issues: list[dict], classifications: list[dict] | None = None) -> dict:
    meta = snapshot.get("extraction") or {}
    expected = meta.get("expected_issues")
    try:
        expected = int(expected) if expected is not None else None
    except (ValueError, TypeError):
        expected = None
    recorded = len(issues)
    issues_with_changelog = sum("changelog" in i for i in issues)
    issues_with_full_changelog = sum(i.get("changelog_complete") is True for i in issues)
    warnings = []
    comment_checks = [issue_comment_coverage(issue) for issue in issues]
    incomplete_comments = [row["key"] for row in comment_checks if not row["pass"]]
    comment_problems = [f"{row['key']}: {message}" for row in comment_checks for message in row["problems"]]
    if incomplete_comments:
        warnings.append("Comment extraction incomplete for: " + ", ".join(incomplete_comments))
    warnings.extend(comment_problems)
    scope_check = scope_ownership(snapshot, issues)
    if not scope_check["pass"]:
        warnings.extend(scope_check["problems"])
    if not meta.get("complete"):
        warnings.append("Jira extraction was not declared complete; totals are for the retrieved subset")
    # expected_issues is the provider universe, before ownership exclusions.
    provider_count = recorded + scope_check["excluded_other_team_issues"]
    if expected is not None and expected != provider_count:
        warnings.append(f"Reconciled {provider_count} provider issues; provider expected {expected}")
    if issues_with_full_changelog < recorded:
        warnings.append("Not all issues have confirmed complete changelogs; historical movement may be undercounted")
    if not (snapshot.get("baseline") or {}).get("available"):
        warnings.append("No sprint-start baseline; original commitment / scope change cannot be confirmed")
    if classifications is not None:
        known = {x["key"] for x in classifications}
        missing = sorted({i["key"] for i in issues} - known)
        if missing:
            warnings.append(f"Missing classifications for {len(missing)} issues")
    else:
        missing = None
    return {"as_of": snapshot.get("as_of"), "sprint": snapshot.get("sprint"),
            "reporting_ownership": scope_check,
            "issues_retrieved": recorded, "issues_expected": expected,
            "provider_reconciled": provider_count,
            "extraction_declared_complete": meta.get("complete") is True,
            "coverage_complete": meta.get("complete") is True and scope_check["pass"] and expected is not None and expected == provider_count and not incomplete_comments,
            "comments_coverage_complete": not incomplete_comments,
            "comments_incomplete_issue_keys": incomplete_comments,
            "comments_total_retrieved": sum(row["retrieved"] for row in comment_checks),
            "issues_with_changelog": issues_with_changelog,
            "issues_with_complete_changelog": issues_with_full_changelog,
            "baseline_available": (snapshot.get("baseline") or {}).get("available") is True,
            "classified_issues": len(classifications) if classifications is not None else None,
            "unclassified_issue_keys": missing, "warnings": warnings}


def complete_status(status: Any, snapshot: dict) -> bool:
    done = (snapshot.get("completed_statuses") or [])
    if not done:
        return False  # never infer arbitrary board mapping from a string
    return str(status or "").casefold() in {str(x).casefold() for x in done}


def completed_in_window(feature_row: dict, snapshot: dict) -> bool:
    return any(complete_status(x.get("to"), snapshot) for x in feature_row.get("status_events", []))


def check_classifications(rows: list[dict], bykey: dict[str, dict]) -> dict[str, dict]:
    mapped = {}
    for i, row in enumerate(rows, 1):
        key = row.get("key")
        if key not in bykey:
            fail(f"classifications record {i}: key {key!r} absent from issues")
        if key in mapped:
            fail(f"duplicate classification for issue {key}")
        for label, allowed in (("work_type", WORK_TYPES), ("execution_mode", EXECUTION_MODES),
                               ("outcome", OUTCOMES), ("confidence", CONFIDENCES)):
            if row.get(label) not in allowed:
                fail(f"{key}: {label} should be one of {sorted(allowed)}; got {row.get(label)!r}")
        if row.get("automation_candidate") not in (True, False, None):
            fail(f"{key}: automation_candidate must be true, false, or null")
        if row["outcome"] == "delivered_verified" and not row.get("evidence"):
            fail(f"{key}: delivered_verified needs source evidence")
        if row.get("evidence") is not None and not isinstance(row.get("evidence"), list):
            fail(f"{key}: evidence must be a list")
        change = row.get("automation_change")
        if change is not None:
            if not isinstance(change, dict):
                fail(f"{key}: automation_change must be an object or null")
            if change.get("stage") not in AUTOMATION_STAGES:
                fail(f"{key}: invalid automation_change.stage")
            if change.get("technology") not in AUTOMATION_TECH:
                fail(f"{key}: invalid automation_change.technology")
            if change.get("changed_in_sprint") not in (True, False, None):
                fail(f"{key}: changed_in_sprint must be boolean or null")
            if change.get("stage") in ("piloted", "in_use", "measured") and not change.get("evidence"):
                fail(f"{key}: pilot/use/measurement requires evidence")
            if change.get("changed_in_sprint") is True and not any(
                    isinstance(e, dict) and e.get("at") and (e.get("url") or e.get("ref"))
                    for e in change.get("evidence", [])):
                fail(f"{key}: changed_in_sprint requires dated evidence")
            if change.get("stage") == "measured":
                measurement = change.get("measurement")
                if not isinstance(measurement, dict) or measurement.get("verified") is not True:
                    fail(f"{key}: measured stage requires a verified measurement")
                fields = ("before_minutes_per_occurrence", "after_minutes_per_occurrence", "occurrences_per_sprint")
                for field in fields:
                    x = measurement.get(field)
                    if isinstance(x, bool) or not isinstance(x, (int, float)) or x < 0:
                        fail(f"{key}: measured stage needs non-negative numeric {field}")
                if measurement["occurrences_per_sprint"] == 0:
                    fail(f"{key}: occurrences_per_sprint cannot be zero for measured benefit")
        mapped[key] = row
    return mapped


def summarize(snapshot: dict, issues: list[dict], labels: list[dict]) -> dict:
    start, end = window(snapshot)
    bykey = indexes(issues)
    labelmap = check_classifications(labels, bykey)
    feats = {x["key"]: feature(x, root_epic(x, bykey), start, end) for x in issues}
    grouped: dict[str, dict] = {}
    global_types = collections.Counter()
    global_modes = collections.Counter()
    global_outcomes = collections.Counter()
    global_missing = []
    warnings = []
    automation_ledger = []
    for key, issue in sorted(bykey.items()):
        f = feats[key]
        epic = f["epic_key"]
        e = grouped.setdefault(epic, {"epic_key": epic, "epic_url": bykey.get(epic, {}).get("url"),
                                       "epic_summary": bykey.get(epic, {}).get("summary"),
                                       "root_work_item_count": 0, "subtask_count": 0,
                                       "issues_total_including_epic_and_subtasks": 0,
                                       "work_types": collections.Counter(), "execution_modes": collections.Counter(),
                                       "outcomes": collections.Counter(), "completed_status_transitions": 0,
                                       "activity_events_count": 0, "manual_support_issue_keys": [],
                                       "automation_candidates": [], "blocker_issue_keys": [],
                                       "verified_delivery_issue_keys": [], "unverified_issue_keys": [],
                                       "unknown_classification_issue_keys": [], "issue_keys": [],
                                       "highlights": []})
        e["issues_total_including_epic_and_subtasks"] += 1
        e["issue_keys"].append(key)
        e["activity_events_count"] += f["in_window_change_count"] + f["in_window_comment_count"]
        if f["is_subtask"]:
            e["subtask_count"] += 1
        if not f["root_counted"]:
            continue
        e["root_work_item_count"] += 1
        if completed_in_window(f, snapshot):
            e["completed_status_transitions"] += 1
        c = labelmap.get(key)
        if c is None:
            global_missing.append(key)
            e["unknown_classification_issue_keys"].append(key)
            e["work_types"]["unknown"] += 1
            e["execution_modes"]["unknown"] += 1
            e["outcomes"]["unknown"] += 1
            global_types["unknown"] += 1
            global_modes["unknown"] += 1
            global_outcomes["unknown"] += 1
            continue
        typ, mode, outcome = c["work_type"], c["execution_mode"], c["outcome"]
        e["work_types"][typ] += 1
        e["execution_modes"][mode] += 1
        e["outcomes"][outcome] += 1
        global_types[typ] += 1
        global_modes[mode] += 1
        global_outcomes[outcome] += 1
        if typ == "operational_support" and mode == "manual":
            e["manual_support_issue_keys"].append(key)
        if c.get("automation_candidate") is True:
            e["automation_candidates"].append(key)
        change = c.get("automation_change")
        if change:
            measured_minutes = None
            if change["stage"] == "measured":
                m = change["measurement"]
                measured_minutes = round((m["before_minutes_per_occurrence"] - m["after_minutes_per_occurrence"]) * m["occurrences_per_sprint"], 2)
            automation_ledger.append({"issue_key": key, "epic_key": epic, "issue_url": issue.get("url"),
                "process": change.get("process") or issue.get("summary"),
                "stage": change["stage"], "technology": change["technology"],
                "changed_in_sprint": change.get("changed_in_sprint"),
                "measured_net_minutes_per_sprint": measured_minutes,
                "evidence": change.get("evidence", []), "measurement": change.get("measurement")})
        if outcome == "blocked" or c.get("blocker"):
            e["blocker_issue_keys"].append(key)
        if outcome == "delivered_verified":
            e["verified_delivery_issue_keys"].append(key)
            e["highlights"].append({"key": key, "summary": issue.get("summary"),
                                    "customer_impact": c.get("customer_impact"), "evidence": c.get("evidence", [])[:4],
                                    "url": issue.get("url")})
        if outcome == "completed_unverified":
            e["unverified_issue_keys"].append(key)
    epic_list = []
    for key, e in sorted(grouped.items()):
        e["work_types"] = dict(sorted(e["work_types"].items()))
        e["execution_modes"] = dict(sorted(e["execution_modes"].items()))
        e["outcomes"] = dict(sorted(e["outcomes"].items()))
        # Signal is descriptive; never a business-value score. A missing history can suppress verified outcomes.
        e["activity_without_verified_delivery"] = (e["activity_events_count"] >= 10 and
            not e["verified_delivery_issue_keys"] and e["root_work_item_count"] > 0)
        epic_list.append(e)
    epic_list.sort(key=lambda x: (-len(x["verified_delivery_issue_keys"]), -len(x["blocker_issue_keys"]), x["epic_key"]))
    cov = coverage(snapshot, issues, labels)
    if not snapshot.get("completed_statuses"):
        warnings.append("No completed_statuses configured: completed-in-window status counts deliberately unavailable")
    if global_missing:
        warnings.append(f"Excluded {len(global_missing)} unclassified root issues from definite labels")
    stages = collections.Counter(x["stage"] for x in automation_ledger)
    technologies = collections.Counter(x["technology"] for x in automation_ledger)
    verified_sprint_automation = [x for x in automation_ledger if x["changed_in_sprint"] is True and x["stage"] in ("in_use", "measured")]
    measured = [x["measured_net_minutes_per_sprint"] for x in automation_ledger if x["measured_net_minutes_per_sprint"] is not None]
    base = {
        "schema_version": "1.0", "generated_from": "local-snapshot-only", "scope": {"sprint": snapshot.get("sprint"), "project_keys": snapshot.get("project_keys"), "as_of": snapshot.get("as_of"), "window_end": end.isoformat()},
        "coverage": cov,
        "metrics": {
            "issues_retrieved_including_epics_subtasks": len(issues),
            "root_work_item_count": sum(x["root_work_item_count"] for x in epic_list),
            "subtask_count": sum(x["subtask_count"] for x in epic_list),
            "work_types": dict(sorted(global_types.items())),
            "execution_modes": dict(sorted(global_modes.items())),
            "outcomes": dict(sorted(global_outcomes.items())),
            "root_manual_operational_support_count": sum(len(x["manual_support_issue_keys"]) for x in epic_list),
            "root_automation_candidate_count": sum(len(x["automation_candidates"]) for x in epic_list),
            "root_verified_delivered_count": sum(len(x["verified_delivery_issue_keys"]) for x in epic_list),
            "root_blocked_count": sum(len(x["blocker_issue_keys"]) for x in epic_list),
            "completed_in_window_transition_count": sum(x["completed_status_transitions"] for x in epic_list) if snapshot.get("completed_statuses") else None,
            "automation_ledger_count_by_stage": dict(sorted(stages.items())),
            "automation_ledger_count_by_technology": dict(sorted(technologies.items())),
            "implemented_automation_changes_in_sprint_count": len(verified_sprint_automation),
            "implemented_ai_changes_in_sprint_count": sum(x["technology"] in ("ai", "mixed") for x in verified_sprint_automation),
            "measured_net_minutes_per_sprint_known_subset": sum(measured) if measured else None,
            "measured_process_count": len(measured),
            "time_saved_note": "Measured total applies only to evidenced measured processes; unknown processes are excluded, not zero. Negative totals are possible."
        },
        "epics": epic_list, "automation_ledger": automation_ledger, "warnings": warnings
    }
    return base


def report_md(rollup: dict) -> str:
    metrics, cov = rollup["metrics"], rollup["coverage"]
    scope = rollup["scope"]
    name = (scope.get("sprint") or {}).get("name", "Unnamed Sprint")
    out = [f"# Sprint Intelligence — {name}", "",
           f"As of: {scope.get('as_of')} | Issues: {cov['issues_retrieved']} | Extraction complete: {cov['coverage_complete']}", "",
           "## Verified metrics (root issues; epics and subtasks excluded)", "",
           f"- Root issues: {metrics['root_work_item_count']}; verified deliveries: {metrics['root_verified_delivered_count']}; blocked: {metrics['root_blocked_count']}.",
           f"- Manually executed operational-support tickets: {metrics['root_manual_operational_support_count']}; automation candidates: {metrics['root_automation_candidate_count']}.",
           f"- Work types: `{json.dumps(metrics['work_types'], sort_keys=True)}`",
           f"- Verified implemented automation changes this sprint: {metrics['implemented_automation_changes_in_sprint_count']}; of those AI/mixed: {metrics['implemented_ai_changes_in_sprint_count']}.",
           f"- Measured net minutes per sprint for evidenced subset: {metrics['measured_net_minutes_per_sprint_known_subset']} (unknown is not zero).", "",
           "## Epic facts (narrative must be reviewed by the Quick agent)", ""]
    for e in rollup["epics"]:
        name = e.get("epic_summary") or "No epic title available"
        out.append(f"### {e['epic_key']} — {name}")
        out.append(f"Root issues: {e['root_work_item_count']} | Verified delivery: {len(e['verified_delivery_issue_keys'])} | Blockers: {len(e['blocker_issue_keys'])} | Operational manual: {len(e['manual_support_issue_keys'])}")
        out.append(f"- Verified issue keys: {', '.join(e['verified_delivery_issue_keys']) or 'None verified'}")
        out.append(f"- Blocked issue keys: {', '.join(e['blocker_issue_keys']) or 'None confirmed'}")
        out.append(f"- Candidate issue keys: {', '.join(e['automation_candidates']) or 'None classified'}")
        if e["activity_without_verified_delivery"]:
            out.append("- Review signal: many tracked activities without evidence-backed delivery (may reflect missing history or valuable support).")
        out.append("")
    out.extend(["## Automation / AI evidence ledger", ""])
    for a in rollup["automation_ledger"]:
        out.append(f"- {a['issue_key']}: {a['technology']} / {a['stage']} / changed in sprint={a['changed_in_sprint']} / measured net minutes={a['measured_net_minutes_per_sprint']} / evidence={len(a['evidence'])} references")
    if not rollup["automation_ledger"]:
        out.append("- No documented automation stage changes in the classified root issues.")
    out.extend(["", "## Coverage / caveats", ""])
    for caveat in cov["warnings"] + rollup["warnings"]:
        out.append(f"- {caveat}")
    out.extend(["", "This file is a deterministic facts draft, **not** a final outcome narrative. The agent must consult evidence and the report template in `references/report.md` before stakeholder publication.", ""])
    return "\n".join(out)


def prepare(args: argparse.Namespace) -> None:
    snapshot = read_json(args.snapshot)
    start, end = window(snapshot)
    if not isinstance(snapshot.get("run_id"), str) or not snapshot["run_id"].strip():
        fail("snapshot.run_id required for frozen source provenance")
    issues = read_jsonl(args.issues)
    bykey = indexes(issues)
    ownership = scope_ownership(snapshot, issues)
    # Work packets must never include known out-of-scope issues even in a draft.
    if not ownership["pass"]:
        fail("Invalid Reporting ownership routing: " + "; ".join(ownership["problems"]))
    feats = [feature(issue, root_epic(issue, bykey), start, end) for issue in issues]
    expected_epics = {f["epic_key"] for f in feats if f["epic_key"] != NO_EPIC}
    contexts = epic_context_index(read_jsonl(args.epics), expected_epics)
    source_manifest = {"run_id": snapshot.get("run_id"), "sprint_id": snapshot.get("sprint", {}).get("id"),
                       "source_sha256": fingerprint({"snapshot": snapshot, "issues": issues, "epics": read_jsonl(args.epics)})}
    packets = packetize(feats, args.max_items, args.max_chars, contexts,
                        source_manifest_sha256=source_manifest["source_sha256"],run_id=source_manifest["run_id"])
    dest = pathlib.Path(args.out)
    write_jsonl(dest / "issue_features.jsonl", sorted(feats, key=lambda r: r["key"]))
    write_jsonl(dest / "work_packets.jsonl", packets)
    write_json(dest / "source_manifest.json", source_manifest)
    cov = coverage(snapshot, issues)
    cov["packets"] = len(packets)
    cov["packet_source_issue_keys"] = sum(len(p["source_issue_keys"]) for p in packets)
    cov["epic_context"] = {"expected": len(expected_epics), "retrieved": len(contexts),
        "complete": sorted(k for k, v in contexts.items() if v["context_status"] == "complete"),
        "partial": sorted(k for k, v in contexts.items() if v["context_status"] == "partial"),
        "unavailable": sorted(k for k, v in contexts.items() if v["context_status"] == "unavailable")}
    write_json(dest / "coverage.json", cov)
    print(f"Prepared {len(issues)} issues into {len(packets)} packets at {dest}")


def merge(args: argparse.Namespace) -> None:
    packets = read_jsonl(args.packets)
    results = read_jsonl(args.results)
    labels, cov = merge_packet_results(packets, results)
    dest = pathlib.Path(args.out)
    write_jsonl(dest / "classifications.jsonl", labels)
    write_json(dest / "packet_coverage.json", cov)
    print(f"Merged {cov['packets_merged']} packet results and {cov['issues_covered']} unique issue classifications")


def aggregate(args: argparse.Namespace) -> None:
    snapshot = read_json(args.snapshot)
    issues = read_jsonl(args.issues)
    labels = read_jsonl(args.classifications)
    data = summarize(snapshot, issues, labels)
    dest = pathlib.Path(args.out)
    write_json(dest / "rollup.json", data)
    (dest / "report-draft.md").write_text(report_md(data), encoding="utf-8")
    print(f"Aggregated {data['metrics']['root_work_item_count']} root issues across {len(data['epics'])} epic groups at {dest}")
    if not data["coverage"]["coverage_complete"] or data["coverage"]["unclassified_issue_keys"]:
        print("WARNING: coverage partial; see rollup.json", file=sys.stderr)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="Create bounded classifier packets from normalized Jira export")
    prep.add_argument("--snapshot", required=True)
    prep.add_argument("--issues", required=True)
    prep.add_argument("--epics", required=True, help="Context-only epic details, including epics outside sprint membership")
    prep.add_argument("--out", required=True)
    prep.add_argument("--max-items", type=int, default=12)
    prep.add_argument("--max-chars", type=int, default=12000)
    prep.set_defaults(func=prepare)
    merged = sub.add_parser("merge-packets", help="Fail-closed merge of isolated parallel worker results")
    merged.add_argument("--packets", required=True)
    merged.add_argument("--results", required=True)
    merged.add_argument("--out", required=True)
    merged.set_defaults(func=merge)
    agg = sub.add_parser("aggregate", help="Check classification and produce deterministic epic rollup")
    agg.add_argument("--snapshot", required=True)
    agg.add_argument("--issues", required=True)
    agg.add_argument("--classifications", required=True)
    agg.add_argument("--out", required=True)
    agg.set_defaults(func=aggregate)
    args = p.parse_args()
    try:
        args.func(args)
    except (ValueError, OSError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
