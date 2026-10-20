# Quick execution DAG — epic-aware parallel analysis (mandatory)

This is an execution contract, not a suggestion. The **orchestrator** alone owns Jira extraction scope, packet dispatch, consistency gates, cross-epic prioritization, final report, `sharpwriter` and publication. Workers analyze evidence; workers do **not** rank the company-wide top five or publish.

## 0. Scope lock — orchestrator, before any parallelism

Resolve the exact Jira cloud/site, board/filter, *one named sprint ID*, effective start/end, timezone and `as_of`. Resolve the Reporting team ownership rule from the board/team field or an explicit approved roster, not from project key alone. For a shared Jira project, exclude DWH-owned work from Reporting sprint counts and portfolio. A linked DWH issue can be gathered as **dependency context** only. If team ownership cannot be established, flag unknown and stop executive publication rather than silently count it.

Record a nonempty `snapshot.run_id`, `sprint.id`, `sprint.publication_id`, query, selected owners, exceptions, and page coverage in `snapshot.reporting_ownership`: `verified=true`, an evidence-based `rule`, `provider_member_count`, `provider_issue_keys`, `excluded_other_team_issues`, `unresolved_issue_keys=[]`. Quick publication gate rejects unknown or unverified ownership. If several active sprints are possible, ask or process separately; never blend their task sets.

## 1. Extract one immutable source universe — orchestrator

1. Discover Jira MCP capabilities and paginate `sprint = <ID>` to exhaustion. The **membership universe** is the unique sprint issue keys (with past/removed membership caveats); record pagination/count/failures. Capture complete descriptions, acceptance links, and all paginated comments on every in-scope issue (including subtasks); collect relevant changelogs. Preserve comment IDs, author reference, created/updated timestamps, per-issue permalinks, provider totals and pagination coverage. Do not silently truncate raw evidence.
2. Map each source record to `issues.jsonl` in the temporary secure run directory. Every row is a *sprint-membership issue*. Resolve parent/subtask chain and `epic_key`. Apply ownership routing: Reporting roots for analysis; other-team tasks only as dependency context, never Reporting delivery.
3. Collect the **unique epic keys** referenced by those issues, including parent epics **outside the sprint**. Fetch each epic **once**, separately from membership. Read its full Jira description, stated objective, acceptance criteria / DoD, status, owner/team, issue links and directly linked relevant Confluence goals/decisions/acceptance. Store as `epic_context.jsonl`, with `context_status=complete|partial|unavailable`, source pointers, and explicit missing fields. No fabricated goals. Preserve the original full context transiently, not in the publication payload.
4. A root without an epic belongs to `__NO_EPIC__`; it still requires individual classification but cannot be reported as a named epic. A sibling task outside the chosen sprint is **not** a sprint accomplishment, even if used as background.
5. Incomplete issue pagination or unresolved ownership blocks a FINAL report. A substantive epic with partial/unavailable context cannot enter executive highlights: fetch missing primary evidence or mark the report DRAFT. Context-only epics and external dependencies are **never added** to sprint ticket totals.

**Outputs, all outside Git:** `snapshot.json`, `issues.jsonl`, `epic_context.jsonl`, optionally `dependencies.jsonl`, paginated extraction manifest and source cache. Freeze inputs before parallel analysis; re-fetch only specific evidence gaps, not the whole sprint.

## 2. Prepare stable epic packets — deterministic local Python

```sh
python scripts/sprint_pipeline.py prepare \
  --snapshot snapshot.json --issues issues.jsonl --epics epic_context.jsonl --out out
```

This fails when any referenced named epic lacks a context row. It emits `out/work_packets.jsonl`, `issue_features.jsonl`, `coverage.json`. Each packet contains:

- `packet_id` (`<epic_key>__NNN`), `epic_key`, and a **compact source-linked** `epic_context` (goal, acceptance, owner, sources, completeness).
- `run_id`, `source_manifest_sha256`, `packet_sha256` plus `source_issue_keys` with exact issue membership and compact in-window issue features.
- Up to 12 items and up to 12,000 JSON characters **including the repeated epic context**. Large epics become multiple packets; the full raw description/changelog remains in the temporary source store for targeted re-reads.

One issue key belongs to **exactly one** worker packet. No worker performs a second bulk MCP scan.

## 3. Bounded parallel workers — semantic classification

If Amazon Quick exposes *actual* parallel child agents, dispatch 2–4 packets concurrently, subject to its supported runtime and rate limits. Prefer epic-level affinity; a large epic's numbered packets may run in parallel. If Quick lacks child-agent execution, run the identical independent packet steps sequentially, **not** via invented tool names or claims of parallelism.

For **each** `packet_id`, supply: frozen sprint/window, assigned `source_issue_keys`, its source-linked epic context, reference decision tree, and permission for **targeted** read-only primary-source checks for missing evidence, including rereading complete comment bodies and context comments preceding sprint start. The worker must distinguish epic **long-term objective** from **what demonstrably changed during this sprint**. It must review each task, relevant subtask evidence and evidence dates, and identify unexpected cross-epic dependencies without reassigning issue ownership.

Worker output (one record per packet in transient `packet_results.jsonl`):

```json
{"packet_id":"DATA-100__001","epic_key":"DATA-100","run_id":"<snapshot.run_id>","source_manifest_sha256":"<source_manifest.source_sha256>","packet_sha256":"<assigned packet hash>","classifications":[{"key":"DATA-101","work_type":"product_feature","execution_mode":"manual","outcome":"in_progress","confidence":"medium","evidence":[],"automation_candidate":false,"automation_change":null,"customer_impact":null,"blocker":null}]}
```

Worker **must** return exactly the assigned issue keys. It cannot create additional issues, global KPIs, final selected highlights, final report prose, confidence inflation or `sharpwriter` approvals. Evidence claims must have traceable Jira/Confluence references and dates for in-window changes. Work done before sprint start can provide context, never be counted as in-sprint outcome. If `evidence_truncated`, unshown comments, or `epic_context.context_truncated_fields` affects any classification or material conclusion, re-open the complete source through Jira/Confluence before issuing that conclusion; cite the exact source reference. If context evidence is insufficient: `unknown`/`unverified` and request a specific targeted lookup.

## 4. Deterministic fan-in — orchestrator

```sh
python scripts/sprint_pipeline.py merge-packets \
  --packets out/work_packets.jsonl \
  --results packet_results.jsonl --out out
```

**Fail closed** if a packet is missing, duplicated, assigned to the wrong epic, or returns missing/extra/duplicate issue keys. Output: `out/classifications.jsonl` and `out/packet_coverage.json`. Compare key universe against `issues.jsonl` and review `coverage.json`; no silent best-effort merge. Merge first, then aggregate; do not aggregate per-worker narrative or add worker counts together.

## 5. Independent review and epic synthesis

Produce `out/classification_review_plan.json` using `quality_gate.py review-plan`. Use separate reviewers or an isolated independent evidence-read pass for 100% mandatory roots and the required routine sample. Reviewers cannot merely read original worker rationale. Fix primary classifications, rerun affected review and re-merge when source results change.

**Epic synthesis** starts only after all packets for that epic pass fan-in and required rechecks. Re-read the complete epic goal/acceptance and only the relevant root outcome evidence; compare planned milestone with actual in-window delta, record what remains blocked, and write `epic_assessments.jsonl`. Keep root/non-epic work, operations and external dependencies distinct. Synthesis can run per epic concurrently; its outputs are **candidates**, not the global priority order.

## 6. Single global ranking — orchestrator only

```sh
python scripts/quality_gate.py assess \
  --snapshot snapshot.json --issues issues.jsonl --epics epic_context.jsonl \
  --classifications out/classifications.jsonl \
  --source-manifest out/source_manifest.json \
  --packets out/work_packets.jsonl --packet-results packet_results.jsonl \
  --plan out/classification_review_plan.json \
  --reviews classification_reviews.jsonl \
  --epic-assessments epic_assessments.jsonl --out out
```

Every reviewer row must echo `classification_review_plan.json.source_sha256`. Each substantive epic assessment must echo `context_sha256` for the exact epic context and the plan `source_sha256`. The gate recalculates the plan from frozen inputs and rejects stale versions.

The orchestrator uses `highlight_selection.json.selected_epic_keys` **as the only approved ordered shortlist**. Rank by verified customer/product change, then materially evidenced strategic internal engineering milestone, not ticket count. Routine-only epics are excluded; DWH-owned epics appear only as dependencies; important incident recovery belongs in reliability/risk. Handle cross-epic duplicates, common blockers, disputed ownership, and ensure chosen highlights belong to the selected sprint and Reporting team.

The independent gate must PASS before drafting FINAL. Then create complete `report.md`, invoke actual `sharpwriter` full Quality Gate, resolve observations, and run `quality_gate.py publish`. Only after both PASS and audience authorization may Quick write the compact allowlisted Parquet snapshot and rebuild `history.parquet`.

## Restart/recovery and proof

Checkpoint once after network export, after each `packet_result`, after review and after publication approval. Stable packet IDs and a frozen source manifest allow retry of only failed packets. If a parent epic changes mid-run, the orchestrator invalidates affected packets/reviews and resynthesizes, not mix versions. Persist `run_id`, packet coverage, source extraction coverage, review denominator, unresolved gaps, selected epic keys and Quality Gate hashes **in transient audit only**; never in GitHub Pages data. Do not claim subagents ran if Quick supports only sequential calls.
