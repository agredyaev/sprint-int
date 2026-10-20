# Sprint Intelligence · GitHub Pages

Minimal static executive dashboard. **Amazon Quick writes approved Parquet; GitHub
Actions does not install Python, Go, DuckDB, uv, npm packages or a backend.**

```text
Amazon Quick + Sprint Intelligence skill + real sharpwriter Quality Gate
    │  temporary approved JSON stays outside Git
    ▼
Quick-side Python / DuckDB writer (only in Quick environment)
    ├── data/sprints/<ID>.parquet   canonical, one per sprint
    ├── data/history.parquet        derived index, rebuilt from canonical files
    └── data/manifest.json         SHA-256/size list, committed last
    │
    ▼
Git commit → GitHub Actions (shell copy + check + tar.gz backup only)
    │
    ▼
GitHub Pages (HTML + CSS + JS + Parquet)
    │
    ▼
Browser → DuckDB-Wasm → SQL → sprint metrics, portfolio and trends
```

### Responsibilities

| Location | Responsibilities | Dependencies |
|---|---|---|
| **Amazon Quick** | Jira/Confluence via MCP; verify Reporting ownership and evidence; independent review; `sharpwriter` full gate; export typed metrics plus approved narrative into Parquet; rebuild history index | Python and DuckDB available in **Quick's** execution environment |
| **Git repository** | Immutable sprint Parquet, derived history index, static UI, full skill | No installed runtime |
| **GitHub Actions** | Explicit allowlist, SHA-256/size verification against Quick-generated manifest, JS tests, `.tar.gz` backup, deploy | GitHub-provided shell, coreutils, Node and Pages actions; **no installations** |
| **Client browser** | Load DuckDB-Wasm and selected Parquet, run queries, render the dashboard | Modern browser; HTTPS access to the site and pinned jsDelivr assets |

**Parquet is the only permanent reporting data format.** The temporary JSON
handoff is never committed. `history.parquet` is a *derived index* inside the
same format, not an independent source of truth. It is rebuilt whenever Quick
adds or corrects a canonical snapshot.

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — execution boundaries, storage ownership, browser read path and known limits.
- [Verification status](docs/VERIFICATION-STATUS.md) — passed and skipped checks, external integration gaps.
- [Execution harness](docs/EXECUTION-HARNESS.md) — exact stage inputs, commands, stop rules, recovery, and test trust boundaries.
- [Sprint update procedure](docs/UPDATE-PROCESS.md) — source extraction, parallel analysis, quality gates, Parquet export, Git push, deployment and recovery.
- [Data contract](docs/DATA-CONTRACT.md) — transient evidence boundaries, approved payload, versioned Parquet v1/v2 schema, validation and publication restrictions.
- [Schema evolution procedure](docs/SCHEMA-EVOLUTION.md) — ordered steps for nullable columns, version changes, mixed-history reads and rollback.
- [Browser read and lifecycle contract](docs/BROWSER-READ-CONTRACT.md) — manifest verification, bounded WASM memory, snapshot consistency, and failure cases.
- [Release integrity contract](docs/RELEASE-INTEGRITY.md) — source universe, staged updates, file manifest, CI allowlist and recovery.
- [Post-audit hardening](docs/POST-AUDIT-HARDENING.md) — fixes F01–F05, tests and residual trust boundaries.
- [Quick orchestration contract](skills/sprint-intelligence/references/orchestration.md) — mandatory worker/fan-in and ranking rules.

The documents in `docs/` describe the **current implementation**. For command and field definitions, the linked source files are authoritative. They do not imply that Amazon Quick subagents, a real sharpwriter invocation or browser DuckDB-Wasm/Parquet integration have been end-to-end verified in a live tenant.

## Repository layout

```text
site/index.html                      static page shell, independent of sprint count
site/assets/styles.css               Linear-reference Light / Dark / System
site/assets/app.js                   UI, navigation, epics and task details
site/assets/data-store.js            DuckDB-Wasm, typed metric SQL, lazy sprint loading
data/sprints/<ID>.parquet            canonical reports, created by Quick
data/history.parquet                 derived historical summary, created by Quick
data/manifest.json                   release integrity seal, created by Quick
ci/stage.sh                          allowlisted, SHA-256-verified staging for Pages
ci/manifest.jq                       exact release manifest contract
.github/workflows/pages.yml         no-runtime-install publication + tar.gz artifact
skills/sprint-intelligence/          complete Amazon Quick skill and quality gates
skills/sprint-intelligence/scripts/pages/export.py
                                     optional Quick-side publisher utility
examples/quick-payload.json          synthetic, allowlisted example (not production)
```

## Epic-aware Quick extraction and parallel analysis

The full execution DAG lives in `skills/sprint-intelligence/references/orchestration.md` and the exact data boundaries in `skills/sprint-intelligence/references/storage-contract.md`. Quick extracts the **chosen sprint's Reporting tasks**, separately retrieves the **full context of all their parent epics (including epics outside that sprint)**, creates epic-scoped worker packets, optionally dispatches bounded parallel agents, performs a fail-closed fan-in, independent re-review, central cross-epic ranking and `sharpwriter` before publishing. DWH-owned issues are only Reporting dependencies. Complete raw source, subagent packets and review material stay transient and outside Git.

## Export a sprint from Amazon Quick

Run the complete skill, including independently verified classification,
`sharpwriter`, and final publication gate. Only after their **actual PASS**
results may Quick produce the allowlisted report. Source Jira exports and
review workspaces must stay outside this repository.

If Quick has its own reliable Parquet writer, it may write the canonical files
and derived index directly **following the exact schema** below. Alternatively,
in Quick's Python environment with DuckDB available, run:

```sh
python skills/sprint-intelligence/scripts/pages/export.py \
  --input "$RUN/approved-sprint.json" \
  --publication-gate "$RUN/out/publication_gate.json" \
  --quality "$RUN/out/quality.json" \
  --selection "$RUN/out/highlight_selection.json" \
  --report "$RUN/report.md" \
  --manifest "$RUN/report-manifest.json" \
  --receipt "$RUN/sharpwriter-receipt.json" \
  --repo /path/to/sprint-intelligence-pages
```

This is **not** a CI command. The exporter rejects real transient JSON inside
the Git repository, refuses to overwrite an existing sprint without a reviewed
`--replace`, validates the allowlist, prepares the updated snapshot, derived index and integrity manifest off-path, then commits them with rollback on ordinary errors. The manifest is committed last; a crash between renames is rejected by CI until Quick completes recovery.
Never mix demo and production snapshots.

The synthetic JSON fixture is not approved for direct export. Integration tests supply synthetic approval artifacts separately; no production gate is bypassed by `--allow-demo`.

Required hash-bound handoff and threat model: [docs/QUALITY-INTEGRITY.md](docs/QUALITY-INTEGRITY.md). Audit findings and limitations: [docs/AUDIT-REMEDIATION.md](docs/AUDIT-REMEDIATION.md).

## Parquet contract

- Each `data/sprints/<ID>.parquet` contains exactly **one** row.
- The row includes `sprint_id`, `ended_on`, `period_label`, `published_at`,
  `is_demo`, eight **typed metric columns** (`verified_time_saved_hours` can be `NULL`), and `report_json` containing
  the allowlisted concise nested executive narrative. This nested field is
  inside **Parquet**, not an independently stored JSON source. For detailed
  analytic SQL on epics/tasks, evolve the schema explicitly rather than inferring
  business semantics from raw Jira fields.
- `data/history.parquet` contains one row per sprint with the same typed summary
  columns, without narrative payloads, ordered by end date descending.
- The browser fetches and checks the release manifest, then loads the compact index and the selected sprint snapshot. It verifies file sizes and SHA-256 digests before registering them with DuckDB-Wasm, and checks exact sprint membership against the manifest.
  Adding history never increases the HTML or JS size.

The current schema deliberately prioritizes backwards compatibility with the
v8 dashboard. Deep columnar analysis of individual tasks would require a
future normalized Parquet schema; do not mistake the current nested JSON string
for native struct columns.

## Publish to GitHub Pages

1. Commit the approved sprint Parquet, regenerated `history.parquet`, **and** the Quick-generated `data/manifest.json` from one verified export.
   The manifest lists exact sprint IDs, physical schema versions, byte sizes and SHA-256 digests. Do not author it by hand.
2. Confirm the audience is authorized to download **all** Parquet assets. Pages
   is static hosting, not row-level access control; private repositories do not
   by themselves make Pages files private.
3. In repository Settings → Pages → **Build and deployment → GitHub Actions**.
4. Push to `main`. The workflow checks structure, stages `site/` plus Parquet,
   uploads a `sprint-history.tar.gz` **workflow artifact** (including manifest), and deploys Pages.

A first deployment deliberately **fails** until Quick produces at least one
Parquet snapshot and its history index. This repository contains only a
synthetic JSON **example**, not fabricated binary Parquet. See
`skills/sprint-intelligence/references/pages-publication.md`.

## Local UI verification (no installs)

Once Quick has exported a snapshot:

```sh
node --test tests/*.test.mjs       # Node built into your dev machine, not npm
bash ci/stage.sh                   # copies to _site/
# Open _site/ using any static HTTP server, not file://
```

DuckDB-Wasm is imported on demand from a version-pinned CDN. A browser needs
CDN access on first load; self-host its assets for offline/corporate CSP use.
CI verifies the exact release file set, SHA-256 digests, sizes and Parquet magic. **A checksum is not a Parquet decoder or a source-authenticity signature.** Quick must validate the physical schema, rows, content, owner evidence and all gates. CI intentionally does not install Python or DuckDB.

**Security:** GitHub Pages publishes the underlying `.parquet` files; never
include raw issue bodies, Jira comments, personal information, secrets, or
sensitive internal management data without explicit authorization.

Jira comment extraction (mandatory): [COMMENT-EXTRACTION.md](docs/COMMENT-EXTRACTION.md). Full pagination and per-issue comment coverage are required for FINAL.
