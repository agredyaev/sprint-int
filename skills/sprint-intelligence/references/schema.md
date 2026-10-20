# Portable intermediary data contract (v1)

The `snapshot.json` schema version `"1.0"` below is the **temporary extraction format**. It is separate from the published Parquet schema version (`sprint.schema_version = 2`); do not copy it into the approved output.

The Quick agent performs MCP calls. `scripts/sprint_pipeline.py` **does not talk to Jira**. It accepts normalized input and provides deterministic preparation + rollups. Preserve source IDs/URLs and record extraction coverage.

## snapshot.json
```json
{
  "schema_version": "1.0",
  "project_keys": ["OPS", "DWH"],
  "site_url": "https://example.atlassian.net",
  "board_id": 42,
  "sprint": {"id": 101, "name": "Sprint 18", "publication_id": "26.21", "start": "2026-10-05T09:00:00+02:00", "end": "2026-10-16T18:00:00+02:00"},
  "as_of": "2026-10-15T18:00:00+02:00",
  "extraction": {"query": "sprint = 101", "complete": true, "expected_issues": 3, "pages": 1, "changelog_complete": false},
  "baseline": {"available": false, "source": null},
  "reporting_ownership": {"verified": true, "rule": "Jira Team field = Reporting; source checked", "provider_member_count": 3, "provider_issue_keys": ["OPS-201", "DWH-123", "DWH-124"], "excluded_other_team_issues": [{"key":"DWH-123","team":"DWH","source_ref":"https://example.atlassian.net/browse/DWH-123","reason":"Confirmed Team field","ownership_verified":true},{"key":"DWH-124","team":"DWH","source_ref":"https://example.atlassian.net/browse/DWH-124","reason":"Confirmed Team field","ownership_verified":true}], "unresolved_issue_keys": []}
}
```

## issues.jsonl (one JSON object per line)
At minimum: `key`, `summary`, `issue_type`, `status`, optional `status_category`, `project_key`, `epic_key`, `parent_key`, `created`, `updated`, `description`, `url`, `delivery_team`, `reporting_scope="in_scope"`. The issue file includes **Reporting** sprint membership only. Snapshot `reporting_ownership.provider_member_count` counts all Jira sprint members; Routing records each excluded key, non-Reporting owner, checked Jira URL and verification reason. `provider_issue_keys` must enumerate every provider sprint member, with exact set equality to Reporting, excluded, and unresolved keys; count is derived from that universe. If ownership is uncertain, record unresolved keys and block final approval. Changelog/epic enrichment outside sprint does **not** change membership count.
Required comment extraction metadata **on each issue**: `comments` (all fetched comment records, including pre-sprint), `comments_total` (provider count, integer >= 0), `comments_pages` (verified read/page count, integer >= 1), `comments_complete` (explicit bool). `comments=[]` with total `0` and `comments_complete=true` is valid only after reading the Jira comments endpoint. Every comment needs a stable `id`, timezone-aware `created`, normalized full-text `body` (empty string is allowed), and source `url` containing `/browse/<issue_key>`; optional `updated` (timezone-aware), `author_account_id`, `author_display_name`. The `body` is transient and untruncated. If the API hides or redacts comment text, record the gap; do not label extraction complete if the missing text could contain relevant context. A comment created before the sprint may be necessary for interpreting a sprint outcome but is not an in-window event.
Optional other fields: `assignee`, `priority`, `labels`, `components`, `resolution`, `resolved`, `story_points`, `time_spent_seconds`, `links`, `sprint_ids`, `changelog`, `is_subtask`.
Each `changelog` item has `{ "at": ISO8601, "field": "status", "from": "In Progress", "to": "Done", "author": "...", "url": "..." }`. Raw Jira structures must be mapped into this schema first; do not pass unparsed Jira API response directly.
Use `epic_key` for the epic association. For subtasks, if the epic is only on parent, resolve the parent -> epic chain prior to processing. Epic issue itself uses its `key` as an epic group key. No-epic issues receive `__NO_EPIC__`.

## epic_context.jsonl (one row per unique referenced parent epic; **not sprint work**)
A named epic may be outside the chosen sprint. The separate context file must still contain it. Fields: `epic_key`, `context_status` (`complete`, `partial`, `unavailable`), `summary`, `description`, `goal`, `acceptance_criteria`, `acceptance_status`, `acceptance_reason`, `scope`, `status`, `owning_team`, `reporting_scope`, `url`, `source_refs`, `reason_missing`. Complete/partial context needs a Jira URL and source pointers; unavailable context needs a reason. Missing row or duplicate key is an error. Keep full raw descriptions only in ephemeral source files; packet excerpts are bounded. More detail: `references/storage-contract.md`.

## Outputs from local prepare
- `issue_features.jsonl`: compact facts on each issue (windowed status transitions, latest in-sprint comment excerpts, recent pre-sprint context comment excerpts, total comment counts, comment extraction status, explicit blocker links/status and scope markers). Excerpts are for routing only; AI reviewers must reopen the complete private source comments for material/ambiguous claims.
- `work_packets.jsonl`: <= 12 issues **and** <= 12k JSON characters per packet, *including* embedded compact epic context and source pointers. Source evidence beyond the limit remains available for targeted retrieval; it is never presumed checked because its excerpt was truncated.
- `coverage.json`: scope and extraction checks + epic-context completeness by key.
- `packet_results.jsonl` (worker output, ephemeral): `{"packet_id":"DATA-100__001","epic_key":"DATA-100","classifications":[{"key":"DATA-101", "work_type":"product_feature", "execution_mode":"unknown", "outcome":"unknown", "confidence":"low", "evidence":[], "automation_candidate":null}]}`. A real worker result also includes `run_id`, `source_manifest_sha256`, and `packet_sha256` copied unchanged from the prepared packet. Each worker covers exactly its assigned keys. `merge-packets` rejects omissions, duplicates, substitutions and unknown packet IDs and produces deterministic `out/classifications.jsonl`.

## classifications.jsonl (one per issue key)
```json
{"key":"DATA-101","work_type":"product_feature","execution_mode":"manual","outcome":"delivered_verified","confidence":"high","evidence":[{"source":"jira","ref":"DATA-101","url":"https://example.atlassian.net/browse/DATA-101","fact":"Acceptance tests passed and release deployed","at":"2026-10-10T10:00:00+02:00"}],"automation_candidate":false,"customer_impact":"Users can export a report without assistance","blocker":null,"estimated_minutes_per_occurrence":null,"frequency_per_sprint":null,"automation_change":null}
```
Allowed values:
- `work_type`: `product_feature`, `product_enhancement`, `bug_fix`, `incident`, `operational_support`, `maintenance`, `platform_enablement`, `discovery`, `administrative`, `unknown`.
- `execution_mode`: `manual`, `scripted_automation`, `ai_assisted`, `ai_automated`, `mixed`, `unknown`.
- `outcome`: `delivered_verified`, `completed_unverified`, `in_progress`, `blocked`, `no_material_change`, `unknown`.
- `confidence`: `high`, `medium`, `low`.
- `automation_candidate`: `true`, `false`, or `null` when unknown.
- `evidence`: array of source pointers and supporting factual claims; unknown evidence is an empty array; mark any claim made without evidence as unverified.

## Counting contract
- `issue_count`: unique current membership issue keys from completed paginated search (or known subset if partial).
- `root_work_item_count`: unique non-subtask tasks, excluding Epic issue records; subtasks shown separately.
- A Jira `Done` **status** can be reported as status, not proof of delivered_verified outcome.
- `completed_in_window`: only confirmed status change to a configured completed state during window (can be approximated from prior/new snapshots with explicit label). `resolved` alone is insufficient if timestamp not in window.
- `manual_work_count`: classify only items with `execution_mode == manual`; `unknown` is excluded from manual denominator and reported separately.
- `AI adoption` and `automation impact` counts are **evidence-backed** and may have a different denominator from total tickets.
- Time saved: only calculate for cases with verified before/after rate * frequency; otherwise report `unquantified` and do not substitute story points.

## automation_change (optional; distinct from an automation candidate)
Only set when an issue documents **an actual automation initiative or change**, not just because the issue was executed with a script. Structure:
```json
{
  "stage": "measured",
  "technology": "rules_script",
  "changed_in_sprint": true,
  "process": "Nightly report refresh",
  "evidence": [{"source":"jira","ref":"DATA-105","url":"https://example.atlassian.net/browse/DATA-105","fact":"Scheduled job enabled","at":"2026-10-10T10:00:00+02:00"}],
  "measurement": {"verified":true,"before_minutes_per_occurrence":15,"after_minutes_per_occurrence":2,"occurrences_per_sprint":40}
}
```
Allowed `stage`: `proposed`, `piloted`, `in_use`, `measured`; `technology`: `rules_script`, `ai`, `mixed`, `unknown`. `changed_in_sprint` must refer to a dated evidenced change. Use `null` when implementation timing is not known. Only `measured` with a verified comparable time measurement permits calculation. Net minutes per sprint = (before − after) × actual observed sprint frequency. Count **known measured subset only**; do not treat unknown opportunities as zero. `AI assisted` is not identical to `AI automated` and a proposed automation is not included in implemented change metrics.
