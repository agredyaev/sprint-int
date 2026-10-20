# Quick Skill audit: sprint + epic context + parallel orchestration

## Review basis
Audited the complete `skills/sprint-intelligence/SKILL.md`, extraction/schema/classification/ranking/report/publication references, `sprint_pipeline.py`, `quality_gate.py`, Parquet allowlist/exporter, and GitHub Pages pipeline from the previous zero-install snapshot. Did not run Amazon Quick itself or Atlassian MCP against a real tenant; observed tests are local deterministic tests.

## Findings and fixes

| Earlier state | Why it mattered | Correction |
|---|---|---|
| `issues.jsonl` included sprint issue records, but epic title and metadata were not guaranteed in task worker context | A parent epic outside sprint was absent from packets; task workers could infer goals from titles | Added mandatory separate `epic_context.jsonl` and source-linked bounded context in **every** epic packet; strict missing-row checks |
| Multi-agent notes suggested 2–4 concurrent calls but no exact fan-in | Duplicate task conclusions, lost packets or divergent epic assignments could enter aggregate | Added concrete packet input/output, `merge-packets` CLI, exact key reconciliation and fail-closed coverage |
| Scope mixed shared Jira boards with Reporting/DWH | DWH delivery could be mistakenly attributed to Reporting | `snapshot.reporting_ownership` plus per-issue `reporting_scope` checks; final Quality Gate requires verified ownership; DWH context belongs to dependency list |
| Epic review did not enforce completeness of fetched goal context | Unsupported material highlights possible | `quality_gate.py assess --epics epic_context.jsonl` rejects FINAL if a substantive epic has incomplete context; DWH epic cannot be chosen |
| `quality_gate.SUBSTANTIVE` accepted `engineering_improvement`, while pipeline's allowed labels did not | Legitimate strategic refactor classifications were rejected | Added explicit label and classifier decision branches |
| Pages/Parquet description could be mistaken for full task archive | Risk of storing Jira text/comments in public artifacts | Defined separate transient raw/source/packet workspace and canonical allowlisted Parquet contract; typed KPI columns + vetted nested `report_json` is **not native columnar task data** |

## Exact execution sequence for Quick

1. Lock sprint ID and Reporting ownership rule; JQL pagination and coverage.
2. Fetch sprint membership issues + parents/subtasks; map Reporting issues to `issues.jsonl`, route DWH as context.
3. Fetch all referenced parent epics **once even if not in sprint**: full goal, description, acceptance, linked Confluence and sources into `epic_context.jsonl`.
4. Run deterministic `prepare --epics`; check context completeness and packet count.
5. Dispatch bounded 2–4 actual Quick subagents by epic/packet if supported; otherwise identical sequential processing.
6. Run `merge-packets` (exact packet ID/epic/key agreement), then independent classification audit and epic synthesis after all packets for an epic finish.
7. Only orchestrator performs cross-epic ranking and deterministic highlight selection via `quality_gate.py assess --epics`.
8. Aggregate, write complete executive report, invoke *actual* `sharpwriter` and publication Quality Gate; publish only on PASS.
9. Quick produces concise one-row canonical Parquet for sprint and rebuilds `history.parquet`; CI stages static Pages with zero Python/uv/npm installations.

## Security and verification boundaries

- This artifact **does not prove** that Amazon Quick supports child-agent parallelism. It discovers the runtime at execution, falls back to sequential, and must not claim concurrent work without real calls.
- The `epic_context.context_status` and gate receipt are structured claims. Local code checks structure and declared coverage; actual sources and independent `sharpwriter` invocation require Quick permissions and execution.
- Full Jira/Confluence content remains in transient local run workspaces **outside Git**. Published Parquet contains only vetted short narrative and metrics. GitHub Pages does not supply row-level access control.
- Parquet exporter remains Quick-side Python/DuckDB only; GitHub Actions and readers install no runtimes. Browser DuckDB-Wasm stays unchanged in this revision.
