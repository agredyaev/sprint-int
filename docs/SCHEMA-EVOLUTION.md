# Parquet schema evolution

## Scope

This procedure applies to the canonical `data/sprints/<ID>.parquet` files and
the derived `data/history.parquet` index. It does **not** change the temporary
Jira extraction schema (`snapshot.json`, `issues.jsonl`, `epic_context.jsonl`).

- Canonical source: one approved Parquet file per sprint ID.
- Writer: Amazon Quick, either with its own compatible writer or
  `skills/sprint-intelligence/scripts/pages/export.py`.
- Reader: `site/assets/data-store.js`, running DuckDB-Wasm in the browser.
- CI: static staging only. CI cannot validate Parquet column types or
  independently verify Quality Gate receipts.

## Version policy

| Version | Status | Physical schema | Payload schema |
|---|---|---|---|
| 1 | Read-only legacy | 13 scalar columns and `report_json` | `sprint.schema_version` absent (or 1) |
| 2 | Current write version | v1 scalar fields + `schema_version BIGINT` + nullable `customer_impact_score DOUBLE` | `sprint.schema_version = 2` |

Physical column order and types are defined in
`skills/sprint-intelligence/scripts/pages/parquet_store.py` (`V1_COLUMNS`,
`V2_FIELDS`). The v1 Parquet file remains unchanged. `report_json` continues
to hold the approved, short narrative; it is not a raw Jira export.

The new v2 `customer_impact_score` is an **optional example metric**, not a
required KPI. Leave it `NULL` until the Reporting team approves its business
definition, measurement, source and evidence. Never populate demonstration
values in production. A missing field is not zero.

## Required sequence for a new column

1. **Specify the meaning.** Record its field name, domain/entity, business
   definition, source, unit, type, null semantics, permitted range and first
   schema version. Define whether the UI will display it. Do not create a
   column for data that is unavailable or unverified.
2. **Classify the change.** A new nullable metric/attribute is additive.
   Reusing a name for a changed meaning, type, unit, or join grain is a
   breaking change. It needs a new field name, new version, and explicit
   reader handling. Do not silently reinterpret historical values.
3. **Increment the version.** Add a new version to the allowlisted schema
   registry in `parquet_store.py`; retain all earlier schemas in the reader.
   Do not reorder, remove or change types within a published version.
4. **Update the approved handoff contract.** Change `validate_report.py` and
   Quick's generation instructions. Unknown fields must still fail closed.
   Optional fields may be absent or `null`; do not manufacture `0`.
5. **Update the writer.** Extend the new physical schema and typed row
   serializer in `parquet_store.py`. Write only the latest version; read back
   and compare each scalar field and the complete approved narrative.
6. **Update the derived index.** Modify `export.py:rebuild_history` to emit
   the new index schema from **all** existing canonical files. Explicitly map
   missing older fields to SQL `NULL` (Python `None`), never zero. Compare
   every rebuilt row with the expected canonical values before replacing
   `history.parquet`.
7. **Update the browser reader.** Adjust the selected `history.parquet`
   columns in `site/assets/data-store.js`. Preserve `null` in JavaScript;
   `Number(null)` is zero and is forbidden for absent metrics. Update
   `site/assets/app.js` only if a new UI field is actually displayed.
8. **Update the release manifest.** Amend `asset_manifest.py` and
   `ci/manifest.jq` if the new version is not currently allowed. Regenerate
   `data/manifest.json` from all canonical files; do not edit digests manually.
   A new schema version must fail closed on old CI until explicitly admitted.
9. **Update contracts and tests.** Change `docs/DATA-CONTRACT.md`, this
   document, the skill storage contract, `examples/quick-payload.json` and
   schema regression tests. Test a v1 snapshot alongside a v2 snapshot,
   absent v2 values, wrong types, unsupported versions, and mixed-history
   index reconciliation.
10. **Generate in Quick.** Complete extraction, independent review, ranking,
   `sharpwriter` and publication gates first. Write a new v2 sprint Parquet.
   Existing sprint IDs remain immutable unless an explicit correction is
   reviewed and `--replace` is used.
11. **Rebuild and audit.** Rebuild `history.parquet` from all canonical files.
    Check version, row count, unique sprint IDs, null semantics and values
    by reading back with DuckDB. Check representative older and newest
    sprints in DuckDB-Wasm. Commit the new sprint, rebuilt history and regenerated manifest together.
12. **Deploy.** GitHub Actions stages and publishes already-produced Parquet.
    Do not add a Python/Go/DuckDB runtime to CI for this migration.

### Execution path

```text
[Change request + measured meaning]
                |
                v
[Classify additive / breaking]
                |
                v
[Schema registry + version + validator]
                |
                v
[Quick writer + history generator]
                |
                v
[DuckDB-Wasm reader + optional UI]
                |
                v
[Legacy v1 + new v2 + NULL regression tests]
                |
                v
[Quick source/review/quality gates]
                |
                v
[New snapshot.parquet + rebuilt history.parquet]
                |
                v
[Read-back + browser test + commit]
                |
                v
[GitHub Actions static deployment]
```

## SQL compatibility

`data/history.parquet` is rebuilt with a single current index schema.
Historical missing values are already represented as nullable columns:

```sql
SELECT sprint_id, schema_version, customer_impact_score
FROM read_parquet('history.parquet')
ORDER BY ended_on DESC, sprint_id DESC;
```

Expected examples:

```text
sprint_id | schema_version | customer_impact_score
26.20     | 1              | NULL
26.21     | 2              | NULL
26.22     | 2              | 85.0  # only with approved measurement
```

For direct SQL across physical sprint files of different versions, use
`union_by_name = true`; otherwise DuckDB may reject mismatched columns:

```sql
SELECT sprint_id, schema_version, customer_impact_score
FROM read_parquet('data/sprints/*.parquet', union_by_name = true);
```

With `union_by_name = true`, older physical files have `NULL` for
`schema_version`, because v1 did not contain that column. Interpret that
physical `NULL` as legacy version 1; **do not** confuse it with the version
values in the rebuilt index. Prefer the versioned Quick reader for full
canonical validation; it enforces exact physical schemas and checks JSON
consistency.

## What is not automatic

- Adding a metric does not automatically create a widget or a business
  definition. UI and SQL changes are explicit.
- This version does not migrate `report_json` into separate epic/task
  columns. That requires a separate grain and schema design.
- The GitHub Pages workflow checks file presence and `PAR1` magic, not
  Parquet semantics. Quick's read-back and source-backed quality gates are
  mandatory.
- `--replace` permits a reviewed correction but does not establish approval.
  Never rewrite old sprint files just to add an optional column.

## Failure and recovery

- **New column in an old-version file:** stop; reject an unexpected schema.
- **Unknown field/version:** stop; update the contract and tests first.
- **Invalid metric type/range:** stop; do not publish.
- **Index rebuild failure:** do not commit; rerun Quick `export.py --index-only`
  after fixing the source or tooling. The canonical sprint remains authoritative.
- **Already-published incorrect value:** repeat evidence review and the final
  Quality Gates; replace that sprint only with `--replace`, rebuild history,
  review both binary changes and publish a new commit.
- **Browser cannot read new schema:** hold deployment or roll back the
  previous combined code-and-data commit. Do not silently drop a column.
