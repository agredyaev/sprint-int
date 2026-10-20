# Architecture

## Components

```text
                  QUICK EXECUTION ENVIRONMENT (private)
  Jira MCP --------+
                   +--> Quick orchestrator --> workers --> independent review
  Confluence ------+                              |
                    sharpwriter + publication gate
                                | PASS only
                                v
                     approved transient JSON
                                |
                     Quick-side Python + DuckDB
                                |
                  +-------------+-------------+
                  |                           |
                  v                           v
         data/sprints/<id>.parquet    data/history.parquet
           canonical snapshot          regenerated index
                  |                           |
                  +-------------+-------------+
                                | commit and push
                                v
                      GIT REPOSITORY (data)
                                |
                                v
              GITHUB ACTIONS (no package installation)
                 checks -> stage -> backup -> deploy
                                |
                                v
                   GITHUB PAGES (static HTTPS)
                                |
                  +-------------+-------------+
                  |                           |
                  v                           v
           HTML / CSS / JS              Parquet assets
                  |                           |
                  +----------+----------------+
                             |
                             v
                       DuckDB-Wasm
                       browser Worker
                             |
                             v
                         executive UI
```

Quick is the **only producer** of report data. GitHub Actions does not query Jira,
execute semantic checks, convert Parquet or run Python. The reader does not
install Python, Go, DuckDB or browser extensions.

## Responsibilities

| Component | Reads | Writes | Execution location |
|---|---|---|---|
| Quick orchestrator | Jira sprint issues, parent epics, targeted Confluence sources | Transient extraction, review results, approved report | Quick workspace |
| Quick workers | Assigned issue packet, epic context, targeted source evidence | One classification result per packet | Quick workspace; parallel only if supported |
| Quality gates | Classification/review evidence and final report | PASS/FAIL receipts | Quick workspace |
| Quick exporter | Approved temporary JSON and existing canonical Parquet | One sprint Parquet and rebuilt history Parquet | Quick-side Python environment |
| Git | Approved Parquet, skill, static source | Versioned commits | Repository |
| GitHub Actions | Repository files | Staged `_site`, workflow backup artifact, Pages deployment | GitHub-hosted runner |
| DuckDB-Wasm | Published history and selected sprint Parquet | In-memory query results | Browser Web Worker |
| UI | Query results | DOM; theme preference in localStorage | Browser |

## Repository map

```text
.github/workflows/pages.yml                   deployment entry point
ci/stage.sh                                   publication allowlist + static copy
site/index.html                               fixed document structure
site/assets/styles.css                        presentation tokens and layout
site/assets/app.js                            selection, rendering, navigation
site/assets/data-store.js                     Wasm initialization and Parquet reads
skills/sprint-intelligence/SKILL.md           Quick execution route
skills/sprint-intelligence/references/         extraction, review, storage contracts
skills/sprint-intelligence/scripts/            Quick-side processing and export
examples/quick-payload.json                   synthetic transfer fixture; not published
data/sprints/<id>.parquet                     Quick-produced canonical reports (after first run)
data/history.parquet                          Quick-produced derived index (after first run)
docs/                                         operational documentation
```

The repository intentionally has no initial production Parquet. Deployment
fails before the first approved Quick export.

## Write path

```text
Sprint selected -> membership paginated -> ownership verified
   -> referenced epic context fetched separately
   -> frozen source snapshot -> bounded epic packets
   -> worker classification -> exact-key fan-in
   -> independent review -> epic synthesis -> global ranking
   -> report.md -> real sharpwriter PASS -> publication gate PASS
   -> approved JSON outside Git -> write/read-back sprint Parquet
   -> rebuild/read-back history Parquet -> review & commit both
   -> GitHub Actions -> Pages
```

A parent epic retrieved for context does not become a sprint issue. Linked DWH
work is dependency context, not Reporting delivery. A worker cannot select
portfolio-wide highlights. See [UPDATE-PROCESS.md](UPDATE-PROCESS.md) for
execution and recovery steps.

## Read path

```text
Browser opens index.html
  -> app.js imports data-store.js
  -> data-store.js imports @duckdb/duckdb-wasm@1.29.0 from jsDelivr
  -> creates Web Worker + in-memory DuckDB instance
  -> fetches data/manifest.json, validates file-list metadata
  -> fetches data/history.parquet and checks SHA-256/size before registration
  -> SQL selects index rows, newest sprint first
  -> app.js populates sprint selector
  -> fetches entire data/sprints/<selected-id>.parquet
  -> SQL selects report_json from its single row
  -> JSON.parse -> render metrics, highlights, epics, tasks, dependencies
  -> selecting another sprint fetches only that sprint's file
```

`data-store.js` caches loaded reports for the current page session. The site
currently downloads **whole Parquet files** into buffers; it does not use
HTTP Range/partial row-group reads. Only per-file lazy loading is implemented.
A page reload is required to see a newly deployed sprint; the current UI does
not poll `data/version.txt` for updates.

## State and consistency

- `data/sprints/<id>.parquet` is canonical. `data/history.parquet` is derived.
  For v1/v2 compatibility and upgrade steps see [SCHEMA-EVOLUTION.md](SCHEMA-EVOLUTION.md).
- Every approved new sprint or reviewed correction rewrites the history index.
- Quick prepares a candidate snapshot and complete index outside the canonical
  paths, checks both, then commits the sprint, index and SHA-256 manifest (last).
  Normal write exceptions trigger rollback. No filesystem primitive atomically
  replaces all three paths: a hard crash may leave partial changes. CI rejects
  hash-inconsistent sets until Quick resumes or rebuilds the index/manifest.
  Git commits must include all three changes.
- Git records binary Parquet revisions; it does not provide readable field diffs.
- `_site` and `artifacts` are outputs, not authoritative stores.
- The workflow archive `sprint-history.tar.gz` is a **30-day workflow artifact**.
  It is not read by the site and does not replace Git history.

## Trust and security boundaries

1. Source descriptions, comments, changelogs, parent epic context, worker
   packets and quality receipts stay in a secure temporary Quick workspace,
   outside this repository.
2. Only allowlisted concise executive content passes to canonical Parquet.
   The exporter checks schema and round-trip, **not** whether an actual
   sharpwriter invocation occurred. Quick must establish that separately.
3. CI allows exactly four static files, checks a Quick-generated manifest for
   expected sprint IDs, versions, lengths, SHA-256 digests and `PAR1` magic,
   and runs JavaScript tests. A matching hash does not prove valid Parquet.
   It does **not** validate Parquet semantics, Reporting ownership, evidence or
   security approval.
4. GitHub Pages serves Parquet as downloadable assets. No row-level protection
   or server-side authorization exists. Anyone able to fetch those asset URLs
   can read the report data. Obtain explicit publication authorization before
   committing internal management reporting.
5. Wasm JavaScript and engine bundles are fetched from jsDelivr on page load.
   This is not a self-contained offline deployment. A restrictive corporate
   CSP or blocked CDN prevents initialization unless assets are self-hosted.

## Explicit limitations

- Current Parquet v2 contains typed scalar metrics and one `report_json`
  string, **not** typed epic/task tables. DuckDB-Wasm uses SQL for metrics and
  extracting that string; nested detail is parsed by JavaScript.
- Full Quick agent concurrency depends on the available runtime. The included
  Python scripts prepare and validate packets; they do not invoke MCP or
  dispatch agents themselves.
- No automatic data refresh occurs. Publication starts only when Quick writes,
  commits and pushes an approved update.
- No independent semantic Parquet verifier runs in GitHub Actions.

## Browser resource bounds and consistency

See [Browser read contract](BROWSER-READ-CONTRACT.md). The client releases each registered sprint Parquet after decoding, caches three parsed reports, serializes SQL reads on its single DuckDB-Wasm connection, and cross-checks typed fields against the history index and narrative payload. These checks are not a substitute for Quick-side semantic review.
