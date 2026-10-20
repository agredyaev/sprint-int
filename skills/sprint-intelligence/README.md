# Sprint Intelligence — for Amazon Quick Desktop

**Import**: Quick Desktop → Customize → Skills → Create → From file → select the ZIP with `SKILL.md` at archive root. Alternatively import the extracted folder through From folder. Quick labels can differ by version.

**Prerequisites**: Atlassian/Jira MCP connector (Confluence optional); permission to read board/sprints/issues/changelogs; access to Python Code Execution and a user-approved workspace folder. No API keys are embedded. The skill never modifies Jira or Confluence.

**First run (paste into Quick)**:

> Use the Sprint Intelligence skill. Identify the active sprint for project **<PROJECT KEY>** using my existing Atlassian MCP connector. Export the full sprint once; produce an evidence-based summary by epic, separating verified progress from ticket activity, risks, operational support, recurring manual processes, automation candidates and AI/script automation actually implemented in this sprint. Use bounded packets and local Python processing. Cite issue URLs, display coverage and uncertainty. Do not modify Jira or Confluence. Before finalizing, independently audit material classifications and select customer/internal product/engineering milestones; exclude routine-only epics from executive highlights. Invoke the existing `sharpwriter` skill for its **full Quality Gate** on the entire report, then run the publication gate. If unavailable, return a DRAFT only. Write the report in Russian.

If the project has multiple active boards/sprints, tell Quick which board or sprint ID to use. For a completed sprint, specify the exact sprint name/ID.

**Epic-aware orchestrator**: Read `references/orchestration.md` and `references/storage-contract.md` first. Fetch sprint membership plus parent epic context separately (including epics outside sprint); run `prepare --epics epic_context.jsonl`, optional 2–4 actual subagent classifiers, `merge-packets`, independent verification, per-epic synthesis, central ranking, `sharpwriter`. DWH/external-owned tickets are dependencies only, never Reporting delivery. Worker packet sources and results remain outside Git.

**Local pipeline**: `SKILL.md` specifies extraction via MCP, normalized `snapshot.json` and `issues.jsonl`, `prepare`, bounded per-packet semantic labeling into `classifications.jsonl`, and `aggregate` to deterministic unranked `rollup.json` and `report-draft.md`, independent review using `quality_gate.py review-plan`, and vetted top-epic selection with `quality_gate.py assess`. Only material customer or strategic internal engineering milestones may enter top highlights; manual/routine-only epics are explicitly excluded. After generating `report.md`, the agent must invoke the existing Quick **`sharpwriter`** skill for its full Quality Gate and run `quality_gate.py publish` before calling the report final.

**Test offline** (optional):
```
python -m unittest discover -s tests -v
python scripts/sprint_pipeline.py prepare --snapshot tests/sample_snapshot.json --issues tests/sample_issues.jsonl --epics tests/sample_epic_context.jsonl --out output
python scripts/sprint_pipeline.py aggregate --snapshot tests/sample_snapshot.json --issues tests/sample_issues.jsonl --classifications tests/sample_classifications.jsonl --out output
python scripts/quality_gate.py review-plan --snapshot tests/sample_snapshot.json --issues tests/sample_issues.jsonl --classifications tests/sample_classifications.jsonl --out output
```

Synthetic test data uses `example.atlassian.net`; it is not connected to any real tenant.

**Current limitations**: The local Python script does not invoke MCP or LLMs itself: the Quick agent does that using its configured connector. Concurrency depends on available runtime capabilities. Estimates of time saved and deployed automation are reported only if source-backed. No historical committed sprint scope can be reconstructed without Jira history or a baseline snapshot.

**Publication requirement:** The skill `sharpwriter` must be installed/enabled separately in Amazon Quick. No bundled code can impersonate that skill. Its absence means the sprint summary remains a clearly marked draft. For the new review format, read `references/review-and-ranking.md`, `references/sharpwriter-quality-gate.md`.

Mandatory execution runbook: [`docs/EXECUTION-HARNESS.md`](docs/EXECUTION-HARNESS.md).
