# Data contract — what is fetched, analyzed, stored and published

## Four distinct domains (never mix them)

| Domain | Exact scope | Location / lifetime | Counts as sprint delivery? |
|---|---|---|---|
| Sprint membership issues | Chosen sprint ID, relevant Reporting-owned root issues plus their Jira membership subtasks/epic records | Secure temporary `issues.jsonl` with raw evidence | Only verified in-window Reporting root outcomes |
| Parent epic/goal context | **All unique parent epics** of chosen sprint tasks, including epics not assigned to sprint; goal, description, acceptance/DoD, linked decisions | Secure temporary `epic_context.jsonl`; full content never goes to Git | **No**; context only |
| Other-team / DWH dependencies | Linked blockers, dependencies or prerequisite milestones to Reporting work | Secure temporary source cache; only approved concise dependency entry in final snapshot | **No** Reporting credit |
| Approved executive snapshot | Final concise approved Reporting epics, selected tasks, dependencies, status and metrics | Canonical `data/sprints/<ID>.parquet` in Git + Pages | Presentation of validated outcomes, not raw Jira archive |

`issues.jsonl` is a **snapshot of target sprint membership** — not every issue under the epic. An epic may span 10 sprints; its objective and prior events explain context, while only its member issues and verified in-window milestone count toward this sprint. A task already Done before sprint start stays background, not new completion. Removed issues and original commitment require changelog or sprint-start baseline; report absence explicitly.

## Normalized `epic_context.jsonl` (transient, one row per named epic)

```json
{"epic_key":"DATA-100","context_status":"complete","summary":"Customer reporting export","goal":"Customers can self-serve downloads","description":"Full source epic description, stored transiently","acceptance_criteria":"Signed-off export and access tests","acceptance_status":"present","scope":"Reporting capability","status":"In Progress","owning_team":"Reporting","reporting_scope":"in_scope","url":"https://example.atlassian.net/browse/DATA-100","source_refs":[{"source":"jira","ref":"DATA-100","url":"https://example.atlassian.net/browse/DATA-100"}],"reason_missing":null}
```

`context_status=complete` requires read primary epic goal/description, acceptance/DoD when defined, and source pointers. `partial` requires accurate `reason_missing` for unavailable acceptance/decision/context and pointers for retrieved fields. `unavailable` requires `reason_missing`, never an invented epic goal. The deterministic packet builder rejects missing/duplicate context rows and records incomplete contexts. Use Confluence only when directly linked/necessary; do not scan entire spaces.

## Canonical published storage in the repository

`docs/QUALITY-INTEGRITY.md` defines required source and publication hashes, frozen runs and export approval inputs. `data/sprints/<ID>.parquet` is the **only canonical report history** (one immutable reviewed sprint snapshot per ID; controlled replacements require re-review). Versioned v1/v2 encoding: exactly one row, typed sprint identifiers and KPI columns, and a **short approved `report_json` column** with the nested portfolio narrative. V2 adds `schema_version = 2` and a nullable example metric `customer_impact_score`. V1 is read-only legacy. It is JSON **inside Parquet**, not a separate persistent JSON file. Epic/task fields are not directly columnar; do not claim otherwise. The browser reads `data/history.parquet` (derived typed summary index), then the selected snapshot. New sprint files do not change HTML size.

The approved snapshot may contain `epics[].tasks[]` only as **short, reviewed descriptions of in-sprint Reporting tasks**, `epics[].objective` as vetted broader epic context, and `dependencies[]` for verified cross-team blockers. Do not publish raw issue descriptions, changelogs, comments, epic raw descriptions, independent reviews, agent packet results, selection audit or unapproved personal data.

`data/history.parquet` is rebuilt by Quick from **all** canonical sprint Parquet files each change; it is a derived index, not independent authority. `tar.gz` archives may back up canonical history but are not site query inputs. CI just stages assets and Parquet — no Python, uv, Go or native DuckDB. DuckDB-Wasm queries the browser-accessible Parquet on user devices.

## Publication handoff and gate

A final transient approved JSON matching `examples/quick-payload.json` is validated by the Quick-side writer. It must be derived from a **real** passing extraction/review/`sharpwriter`/publication run, not merely a payload with self-declared `quality="passed"`. Exporter schema currently verifies allowlisted fields, statuses, Reporting ownership, Jira URLs, KPI consistency and one-row Parquet round-trip, but it **cannot cryptographically authenticate** past skill invocations. The orchestrator must match selection and SHA receipts while creating the handoff.

Before Git push: full Quality Gate PASS, stakeholder/audience authorization, no raw data in Git, canonical Parquet read-back, `history.parquet` rebuilt, snapshot-vs-index reconciliation and known source coverage. GitHub Pages files are downloadable to users with URL access; repo privacy alone is insufficient.

## Required schema evolution route

Before a new Parquet column is introduced, read and apply
`docs/SCHEMA-EVOLUTION.md` inside this installed skill. The contract:
(1) define semantics/type/unit/source/null behavior; (2) classify additive vs
breaking; (3) increment physical schema version; (4) update allowlists and
Quick writer; (5) update history index with SQL NULL for missing older data;
(6) update DuckDB-Wasm SQL and UI if displayed; (7) test mixed old/new
sprints; (8) write only the new version after all real quality gates; (9)
rebuild and read back history before committing both files. **Do not rewrite
old sprint files or coerce absent metrics to zero.** The Quick exporter
currently writes only v2 and reads v1/v2. CI cannot perform this migration.

Release consistency: Quick must generate `data/manifest.json` with exact IDs, schema versions, sizes and SHA-256 after validating every Parquet. CI validates this manifest without parsing Parquet; DuckDB-Wasm checks the hashes before querying. See `docs/RELEASE-INTEGRITY.md`.
