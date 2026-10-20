#!/usr/bin/env python3
"""Generate six fictional Parquet sprint snapshots for the public demo.

This script does not invoke Jira, Amazon Quick, reviewers, or sharpwriter.
Quality flags in the synthetic example are display fixtures, NOT attestations.
It deliberately bypasses the live publication approval gate and is not a
production export path. Refuses to write into an existing data store.
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/sprint-intelligence/scripts/pages"))
from export import publish_transaction  # noqa: E402
from parquet_store import read_snapshots  # noqa: E402
from validate_report import validate  # noqa: E402

PERIODS = (
    ("2026-07-27", "2026-08-07"),
    ("2026-08-10", "2026-08-21"),
    ("2026-08-24", "2026-09-04"),
    ("2026-09-07", "2026-09-18"),
    ("2026-09-21", "2026-10-02"),
    ("2026-10-05", "2026-10-16"),
)
STATUSES = (
    ("PROGRESSING", "PROGRESSING", "PROGRESSING", "PROGRESSING", "PROGRESSING", "PROGRESSING", "PROGRESSING"),
    ("PROGRESSING", "PROGRESSING", "PROGRESSING", "PROGRESSING", "PROGRESSING", "DELIVERED", "PROGRESSING"),
    ("PROGRESSING", "PROGRESSING", "AT_RISK", "PROGRESSING", "AT_RISK", "DELIVERED", "PROGRESSING"),
    ("DELIVERED", "PROGRESSING", "BLOCKED", "PROGRESSING", "AT_RISK", "DELIVERED", "PROGRESSING"),
    ("DELIVERED", "DELIVERED", "BLOCKED", "PROGRESSING", "AT_RISK", "DELIVERED", "PROGRESSING"),
    ("DELIVERED", "DELIVERED", "BLOCKED", "PROGRESSING", "AT_RISK", "PROGRESSING", "PROGRESSING"),
)
OUTCOMES = (
    (
        "Sales KPI ownership and baseline agreed.",
        "Forecast completeness rules approved for trial.",
        "Finance planning KPI mapping drafted.",
        "Reporting API inventory completed.",
        "Legacy report consumer inventory started.",
        "Finance access roles catalogued.",
        "Regional rollout cohorts identified.",
    ),
    (
        "Sales KPI pilot definitions signed off.",
        "Forecast validation checks implemented in test.",
        "Finance plan vs forecast requirements accepted.",
        "Reporting API contract agreed.",
        "Legacy migration dependencies mapped.",
        "Finance access ownership matrix accepted.",
        "Regional attribute mapping approved.",
    ),
    (
        "Sales pilot dashboard accepted for business testing.",
        "Forecast thresholds exercised against sample loads.",
        "Finance integration design exposed a DWH schema risk.",
        "Reporting API adapter passed integration tests.",
        "Legacy export mismatch discovered before cutover.",
        "Finance access pilot group provisioned.",
        "First regional rollout cohort reviewed.",
    ),
    (
        "Executive sales view released in the illustrative scenario.",
        "Forecast failure notifications tested.",
        "Finance dashboard integration blocked by the DWH model.",
        "Reporting API fallback path integrated.",
        "Legacy export remediation uncovered a regression.",
        "Finance access provisioning pilot completed.",
        "Second regional cohort onboarded.",
    ),
    (
        "Sales reporting access expanded to additional regions.",
        "Forecast refresh blocking controls deployed.",
        "Finance integration remains blocked by DWH-4812.",
        "Reporting API compatibility edge cases passed.",
        "Legacy export incompatibility remains unresolved.",
        "Finance role-based onboarding completed.",
        "Regional documentation and onboarding prepared.",
    ),
    (
        "Sales adoption and alerting review completed.",
        "Forecast failure handling and escalation verified.",
        "Finance dashboard remains blocked by the DWH model.",
        "Reporting API compatibility milestone completed.",
        "Legacy retirement deferred pending export fixes.",
        "Finance access extended to a second cohort.",
        "Third regional rollout cohort acceptance started.",
    ),
)
SUMMARIES = (
    "Teams agreed the initial sales KPI baseline, finance scope, API contract inventory and rollout cohorts.",
    "Sales KPIs and finance access ownership advanced; reporting dependencies were documented.",
    "Sales pilot reached business review; finance integration and legacy exports developed delivery risks.",
    "Sales executive view launched in this fictional scenario while DWH modeling blocked finance integration.",
    "Forecast refresh controls reached release; finance planning and legacy retirement remain constrained.",
    "Sales adoption and reporting API controls advanced; the finance dashboard remains blocked on DWH.",
)
PULSES = (
    "Baseline sprint: seven Reporting initiatives under active review.",
    "Access ownership and sales KPI definitions reached review milestones.",
    "Business validation expanded; two initiatives require management attention.",
    "Sales release milestone completed; one external finance dependency is blocking delivery.",
    "Forecast safeguards released; manual work decreased as automation expanded.",
    "Sales rollout progressed and forecast guardrails stabilized; finance planning remains blocked.",
)
ATTENTION = (
    "Confirm implementation dates for the shared DWH finance model.",
    "Agree Finance dashboard acceptance and source-model ownership.",
    "DWH model handoff and legacy export mismatch threaten planned milestones.",
    "Finance integration waits for DWH dimensional model delivery.",
    "Finance integration remains blocked; legacy export compatibility needs a decision.",
    "Confirm DWH-4812 handoff date and legacy retirement decision.",
)
HOURS = (None, 2.0, 4.0, 9.0, 14.0, 18.0)
MANUAL = (41, 40, 38, 37, 35, 34)
CANDIDATES = (5, 5, 4, 4, 3, 2)
AUTOMATED = (0, 0, 1, 1, 1, 1)
MATERIAL = (1, 1, 2, 3, 3, 3)
REVIEWED = (29, 31, 34, 36, 39, 42)


def _label(start: str, end: str) -> str:
    a = date.fromisoformat(start)
    b = date.fromisoformat(end)
    return f"{a.day} {a.strftime('%b')} – {b.day} {b.strftime('%b %Y')}"


def generate() -> list[dict]:
    template = json.loads((ROOT / "examples" / "quick-payload.json").read_text(encoding="utf-8"))
    result = []
    for i, (start, end) in enumerate(PERIODS):
        payload = copy.deepcopy(template)
        s = payload["sprint"]
        s.update(
            schema_version=2, id=f"26.{16+i}", started_on=start,
            ended_on=end, period_label=_label(start, end),
            published_at=(date.fromisoformat(end) + timedelta(days=1)).isoformat() + "T08:00:00Z",
            is_demo=True, team="Reporting & Analytics (fictional)",
            reviewed_issues=REVIEWED[i], executive_summary=SUMMARIES[i],
            pulse=PULSES[i], attention=ATTENTION[i],
            attention_owner="Illustrative decision owner: Data Platform",
        )
        m = payload["metrics"]
        m.update(
            material_outcomes=MATERIAL[i],
            blocked_initiatives=STATUSES[i].count("BLOCKED"),
            at_risk_initiatives=STATUSES[i].count("AT_RISK"),
            verified_time_saved_hours=HOURS[i], manual_operations=MANUAL[i],
            automation_candidates=CANDIDATES[i],
            automation_delivered=AUTOMATED[i],
            active_initiatives=len(STATUSES[i]),
            customer_impact_score=None,
        )
        for j, epic in enumerate(payload["epics"]):
            epic["status"] = STATUSES[i][j]
            epic["delivered"] = OUTCOMES[i][j]
            epic["highlight_rank"] = (1 + j) if j < MATERIAL[i] else None
            epic["importance"] = "important" if j < MATERIAL[i] else "normal"
            if epic["jira_key"] == "TABLEAUBI-41862":
                epic["risk"] = ("DWH model delivery blocks implementation." if i >= 3
                                else "DWH source-model handoff date remains uncertain." if i == 2 else "")
                epic["planned_next"] = "Await DWH-4812 model handoff." if i >= 3 else "Confirm source model mapping and delivery dates."
            elif epic["jira_key"] == "TABLEAUBI-41201":
                epic["risk"] = "Export mismatch threatens retirement deadline." if i >= 2 else ""
            else:
                epic["risk"] = ""
            for k, task in enumerate(epic["tasks"]):
                task["status"] = ("DELIVERED" if j < MATERIAL[i] and k == 0
                                  else STATUSES[i][j])
                task["outcome"] = OUTCOMES[i][j]
        deps = payload["dependencies"]
        deps[0]["status"] = (
            "BLOCKED" if i >= 3 else "AT_RISK" if i == 2 else "PROGRESSING"
        )
        deps[1]["status"] = "DELIVERED" if i >= 3 else "PROGRESSING"
        # These flags are synthetic presentation fixtures, never real approvals.
        payload["quality"] = {key: "passed" for key in template["quality"]}
        validate(payload)
        result.append(payload)
    return result


def main() -> None:
    dest = ROOT / "data"
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit("Refusing to overwrite any existing release data; this generator is demo-only.")
    payloads = generate()
    for p in payloads:
        publish_transaction(ROOT, p, allow_demo=True)
    restored = read_snapshots(dest / "sprints", allow_demo=True)
    if [r["sprint"]["id"] for r in restored] != [r["sprint"]["id"] for r in reversed(payloads)]:
        raise AssertionError("Demo Parquet read-back order mismatch")
    print("Generated:", ", ".join(p["sprint"]["id"] for p in payloads))
    print("Index:", dest / "history.parquet")
    print("Manifest:", dest / "manifest.json")
    print("All records are SYNTHETIC. No real Jira or sharpwriter approval.")


if __name__ == "__main__":
    main()
