# Release consistency contract

## Objective

Reject partial Parquet updates and unintended static assets without installing a build runtime in GitHub Actions. This is a file-consistency check; it is not proof of Jira data truth or a trusted Quick/sharpwriter invocation.

## Quick producer steps

```text
Jira sprint key universe + cited Reporting/DWH scope
    -> transient worker packets -> independent checks -> sharpwriter
    -> approved payload + bound publication gate
    -> stage new <ID>.parquet, validate full Parquet read-back
    -> rebuild and validate history.parquet across every sprint
    -> create manifest.json (exact ID list, sizes, SHA-256)
    -> replace sprint, history, then manifest LAST
    -> Git commit ALL changed data paths, then push
```

`skills/sprint-intelligence/scripts/pages/export.py` implements this sequence via `publish_transaction`. The writer uses a temporary directory on the same filesystem. On ordinary exceptions it restores the previous canonical sprint/index/manifest. A process termination between renames is not an atomic multi-file transaction: the previously committed manifest no longer matches, so CI fails. Recover by re-running a newly approved export or, after verifying the canonical snapshots, `export.py --index-only`.

## Manifest shape

```json
{
  "format": "sprint-intelligence-parquet",
  "manifest_version": 1,
  "history": {"path":"history.parquet", "size":1234, "sha256":"<64 lowercase hexadecimal digits>"},
  "sprints": [
    {"id":"26.21", "path":"sprints/26.21.parquet", "schema_version":2,
     "size":2345, "sha256":"<64 lowercase hexadecimal digits>"}
  ]
}
```

The exporter generates this file only **after** reading back the complete set. Do not construct it manually or infer its values from the sprint title. It is a deterministic consistency seal, not a signed attestation. A malicious actor able to change both Parquet and manifest can forge a matching pair. External approvals are outside the CI trust boundary.

## CI staging

`ci/stage.sh` uses preinstalled Bash, `jq`, `sha256sum`, and coreutils. It fails if the manifest is absent or malformed; filenames or IDs differ; hashes or lengths mismatch; files contain invalid `PAR1` magic; symlinks or extra data files are present; or `site/` contains anything other than `index.html`, `assets/app.js`, `assets/data-store.js`, and `assets/styles.css`.

CI **does not parse Parquet row groups or validate schema**. Quick must run a real DuckDB round-trip (including mixed-v1/v2 history) before any commit. CI also does not prove that Jira exclusion evidence, independent subagents, or sharpwriter checks actually occurred. A real tenant integration test is required prior to unattended deployment.

## Recovery

1. Stop publication; do not commit an unmatched sprint/index/manifest set.
2. Validate every canonical sprint in Quick. If a newly staged sprint is unapproved, remove it before rebuilding.
3. Run `python skills/sprint-intelligence/scripts/pages/export.py --repo /path/to/repo --index-only` in Quick, using `--allow-demo` only for synthetic datasets.
4. Re-run full Parquet read-back and CI staging checks.
5. Commit sprint(s), index and manifest in a single reviewed Git commit. If the old manifest was already published, deployment remains blocked until all new hashes match.

For an approved correction, rerun both quality gates with new evidence and use `--replace` with all original approval inputs. `--index-only` does not authorize unreviewed content edits.

## Local staging directory safety

`ci/stage.sh` refuses `.`/`..`, symlinked output paths and a pre-existing
output directory without `.sprint-intelligence-stage`. This prevents the
previously unchecked recursive delete of arbitrary user directories. A new
output directory is marked only after allowlisted content is staged.
The marker is an implementation detail, not an approval or authenticity proof.
