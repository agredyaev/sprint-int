# Browser Parquet read contract

## Scope

This document describes the implemented DuckDB-Wasm read path. It does not certify the Amazon Quick source analysis or `sharpwriter` execution.

## Inputs

- `data/manifest.json`: release file list, byte sizes, SHA-256 hashes, sprint IDs and schema versions.
- `data/history.parquet`: one typed row per sprint, without narrative payloads.
- `data/sprints/<ID>.parquet`: one row per sprint; typed metrics and an approved compact `report_json` narrative.

The browser does not fetch source Jira descriptions, comments or changelogs.

## Read sequence

```text
Browser starts
    |
    v
Fetch manifest.json (no-store)
    |
    v
Reject duplicate/invalid IDs, paths, schema versions, lengths or hashes
    |
    v
Instantiate DuckDB-Wasm; open one connection
    |
    v
Fetch history.parquet -> verify bytes/hash -> register -> SQL read
    |
    v
Compare exact sprint IDs and schema versions with manifest
    |
    v
Display index; no sprint narrative fetched yet
    |
    v
User chooses sprint
    |
    v
Fetch only sprints/<ID>.parquet -> verify size and SHA-256
    |
    v
Register in DuckDB-Wasm -> SELECT * -> require exactly one row
    |
    v
Validate physical columns, version, metadata and metrics against
    report_json AND history.parquet
    |
    +-- mismatch --> Reject sprint; show load error
    |
    v
Drop registered sprint Parquet from DuckDB-Wasm
    |
    v
Cache up to 3 parsed compact reports in JavaScript
    |
    v
Render dashboard
```

## Resource lifetime

- The history index remains registered while the store is open.
- Each sprint Parquet file is dropped immediately after decoding and verification, including failed SQL reads.
- Only three parsed sprint reports are cached. The least recently used entry is evicted on insertion of a fourth distinct report.
- Requests on the shared DuckDB connection are serialized. Concurrent requests for the same sprint share one pending load.
- `close()` waits for pending reads, closes the connection and terminates the worker.
- Initialization failures attempt to close the connection and terminate the worker.

## Client-side consistency checks

1. The manifest has distinct, safe sprint IDs and exact paths.
2. `history.parquet` contains exactly the sprint IDs and schema versions listed in the manifest.
3. A selected sprint contains exactly the physical columns defined by its v1 or v2 schema.
4. Typed columns, embedded report fields, and the history index agree on sprint ID, schema version, period, publication metadata, demo flag and all supported metrics.
5. Required count metrics are finite non-negative integers. The hours-saved metric and the additive v2 customer-impact metric can be `NULL` where allowed.
6. Unknown columns, missing mandatory numeric values, wrong types, inconsistent snapshots and failed hashes stop that sprint from rendering.

These comparisons detect inconsistent releases. They do not establish that Jira evidence is truthful or that the publisher is authorized. A valid SHA-256 value in a public manifest is not a signature.

## Limits and verification

- Files are fetched completely before registration. No HTTP Range optimization is currently used.
- Each Parquet file is limited to 2 MB by the producer and manifest contract. The history index is also subject to that limit.
- Static browser tests use a mock DuckDB file API. They exercise hash verification, bounded caching, read sequencing, error recovery and row consistency, but not the actual WASM binary.
- DuckDB 1.5.6 native round-trip of the v2 physical schema, including `NULL`, has been tested separately. This does not prove WASM compatibility.
- A real browser test using the pinned DuckDB-Wasm CDN and a Quick-generated Parquet release is required before production publication.
- Availability of the pinned third-party CDN is a runtime dependency. Vendor approved assets locally if offline execution or independent asset control is required; this is not implemented.

## Run tests

```sh
node --test tests/*.test.mjs
python3 -m unittest discover -s skills/sprint-intelligence/tests -v
```

The Python tests belong to the Quick-side skill and are not run by GitHub Actions. Integration tests requiring DuckDB are skipped where the package is not installed.
