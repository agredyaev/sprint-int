# Sprint Intelligence

Amazon Quick analyzes Jira sprint evidence. The repository stores approved sprint snapshots as Parquet and serves them through GitHub Pages.

## Execution boundary

| Component | Work | Output |
|---|---|---|
| Amazon Quick | Fetch Jira/Confluence evidence; resolve Reporting ownership; classify issues; review findings; rank epics; invoke `sharpwriter` | Transient approved report and gate artifacts |
| Quick Python + DuckDB | Validate the approved report, write Parquet, rebuild index, seal manifest | `data/sprints/<ID>.parquet`, `data/history.parquet`, `data/manifest.json` |
| GitHub Actions | Verify release file set, sizes and SHA-256; stage static assets; deploy | GitHub Pages artifact |
| Browser | Validate the manifest and Parquet files; query with DuckDB-Wasm; render summaries | Read-only dashboard |

Production reports require a passing classification review, `sharpwriter` receipt and publication gate. Test data never constitutes evidence of those checks. Details: [execution harness](docs/EXECUTION-HARNESS.md) and [quality integrity](docs/QUALITY-INTEGRITY.md).

The repository does not store raw Jira issues, full comments, changelogs, classification packets or review transcripts. These remain in Quick's restricted run workspace. GitHub Pages exposes the published Parquet files to its audience; repository privacy does not establish Pages access control.

## Source layout

| Path | Purpose |
|---|---|
| `skills/sprint-intelligence/SKILL.md` | Amazon Quick entry point |
| `skills/sprint-intelligence/references/` | Extraction, classification, review and reporting rules |
| `skills/sprint-intelligence/scripts/` | Deterministic validation and Parquet export |
| `docs/` | Operational and storage contracts |
| `site/index.html`, `site/assets/` | HTML, CSS and DuckDB-Wasm client |
| `data/sprints/<ID>.parquet` | One typed row per sprint, including approved `report_json` |
| `data/history.parquet` | Derived, typed sprint index |
| `data/manifest.json` | Sprint IDs, schema versions, sizes and SHA-256 hashes |
| `ci/stage.sh` | Allowlisted Pages staging |
| `examples/` | Synthetic fixtures and generator |
| `tests/` | Browser and staging tests |

## Run a sprint in Quick

1. Select the sprint ID, time range and Reporting ownership rule. Fetch the exact membership set.
2. Fetch paginated comments, issue histories and parent epic context, including epics outside the sprint.
3. Run the deterministic `prepare` step, then classify every packet with bounded workers.
4. Merge packets by exact issue keys. Perform independent evidence review and epic assessment; run `assess`.
5. Produce the selected executive report, invoke `sharpwriter`, resolve failures and run `publish`.
6. Export the approved snapshot through Quick-side Python and DuckDB. Rebuild history and manifest.
7. Commit the three release artifacts, then deploy Pages.

Commands, required input files and retry rules: [EXECUTION-HARNESS.md](docs/EXECUTION-HARNESS.md). For a shared Jira project, DWH work is dependency context, not Reporting delivery. Incomplete pagination, unresolved ownership, missing approval or failed gates prevent FINAL. Without Python, Quick can produce a marked DRAFT, not a validated release.

## Parquet export

Run in Quick's execution environment, with Python and DuckDB installed, after the actual publication gates pass. The JSON and receipt files must remain **outside** the repository.

```sh
python skills/sprint-intelligence/scripts/pages/export.py \
  --input "$RUN/approved-sprint.json" \
  --publication-gate "$RUN/out/publication_gate.json" \
  --quality "$RUN/out/quality.json" \
  --selection "$RUN/out/highlight_selection.json" \
  --report "$RUN/report.md" \
  --manifest "$RUN/report-manifest.json" \
  --receipt "$RUN/sharpwriter-receipt.json" \
  --repo /path/to/sprint-int
```

The exporter writes schema v2; v1 remains readable. The report's typed metric columns must agree with `report_json`. `history.parquet` is rebuilt from canonical sprint files. SHA-256 checks detect file changes; they do not authenticate Jira evidence or `sharpwriter` invocation. Schema changes follow [SCHEMA-EVOLUTION.md](docs/SCHEMA-EVOLUTION.md).

## Demo data

The six committed snapshots `26.16`–`26.21` are **synthetic** (`is_demo=true`). They are not outputs of Jira, Amazon Quick, reviewers or `sharpwriter`.

Regenerate only in a checkout without existing `data/` contents:

```sh
uv run --with duckdb==1.5.6 python examples/generate_demo.py
```

See [DEMO-DATA.md](examples/DEMO-DATA.md). Do not mix demo and production snapshots.

## Deploy and verify

Set **Settings → Pages → Build and deployment → GitHub Actions**. The workflow builds on `main`; no Python, Go, DuckDB or package installation runs in CI.

```sh
node --test tests/*.test.mjs
bash ci/stage.sh
```

`stage.sh` rejects missing or unexpected files, mismatched hashes and unsafe output directories. Open the staged site over HTTP(S), not `file://`. DuckDB-Wasm loads from a pinned CDN URL; clients require access to it.

**Verification limits:** Python and JS tests cover deterministic contracts. They do not prove live Atlassian extraction, independent worker reasoning, an actual `sharpwriter` run or successful browser decoding of a Quick-generated release. See [VERIFICATION-STATUS.md](docs/VERIFICATION-STATUS.md).

## Reference documents

- [DATA-CONTRACT.md](docs/DATA-CONTRACT.md): transient records, output schema and ownership.
- [COMMENT-EXTRACTION.md](docs/COMMENT-EXTRACTION.md): full comment pagination and timestamps.
- [QUALITY-INTEGRITY.md](docs/QUALITY-INTEGRITY.md): gate artifacts and hash bindings.
- [RELEASE-INTEGRITY.md](docs/RELEASE-INTEGRITY.md): release assembly, verification and recovery.
- [BROWSER-READ-CONTRACT.md](docs/BROWSER-READ-CONTRACT.md): browser checks and memory bounds.
- [UPDATE-PROCESS.md](docs/UPDATE-PROCESS.md): export, deployment and rollback.
- [ARCHITECTURE.md](docs/ARCHITECTURE.md): components and trust boundaries.
- [AUDIT-REMEDIATION.md](docs/AUDIT-REMEDIATION.md), [POST-AUDIT-HARDENING.md](docs/POST-AUDIT-HARDENING.md): prior defects and fixes.
