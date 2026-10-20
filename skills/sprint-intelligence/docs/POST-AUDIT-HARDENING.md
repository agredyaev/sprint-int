# Post-audit hardening — 2026-10-18

Baseline: local commit `8fa6275`; follow-up findings F01–F05. This document reports changes and remaining assurance limits. No live Jira/Quick tenant or deployed browser was tested.

| Finding | Change | Automated regression | Residual condition |
|---|---|---|---|
| F01 Source universe | `scope_ownership()` uses exact `provider_issue_keys` equality and per-excluded-key `{key,team,source_ref,reason,ownership_verified}`; legacy count-only list rejected | `test_release_hardening.py` plus old ownership tests | Jira ownership attestations are asserted by Quick; independent source review is still required |
| F02 CI staging | `data/manifest.json` is generated from Quick-read-back Parquet. CI rejects altered hashes/sizes, unknown file sets, symlinks and unlisted `site/` assets; stages an explicit four-file allowlist | `tests/staging.test.mjs` | A matching manifest does not prove a valid Parquet file or actual approval; Quick must parse and verify |
| F03 Interrupted update | Candidate sprint + index are built/validated off-path. Existing bytes are kept for exception rollback; SHA manifest installed last. Browser also checks manifest hashes and sprint IDs | Transaction rollback tests; `tests/site.test.mjs` | A hard crash between renames is not a true atomic multi-file commit; mismatched manifest blocks CI until recovery |
| F04 Numeric contract | `BIGINT` metrics require `type(v) is int`, rejecting float/boolean; nullable DOUBLE is separate | `test_release_hardening.py` | Report numeric evidence itself remains a Quick review responsibility |
| F05 Standalone skill | Full `docs/` contracts copied under `skills/sprint-intelligence/docs/`, relative links fixed, file-mirror regression | `test_standalone_normative_references_are_relative` and link scanner | Publishing still requires access to a Pages repository and a Quick execution environment |

## Release checks

```sh
python -m unittest discover -s skills/sprint-intelligence/tests -v
node --test tests/*.test.mjs
bash -n ci/stage.sh
node --check site/assets/app.js
node --check site/assets/data-store.js
```

The Node staging fixture intentionally uses padded `PAR1` bytes and tests the **manifest/staging guard only**. It is not a Parquet integration test. Two Python tests using real DuckDB are skipped if DuckDB is absent; neither GitHub Actions nor the browser installs Python. Before enabling unattended publication, execute the complete Quick + Jira/Confluence + sharpwriter + DuckDB export/read-back + DuckDB-Wasm browser test on controlled, audience-approved data.

## Trust model

- `manifest.json` is a checksum ledger, **not a digital signature**.
- The data provider and Quick executor can fabricate matching manifests and Parquet. Trusted extraction and independent review cannot be proved by this repository alone.
- GitHub Pages hosts readable Parquet. Do not publish confidential internal records on a publicly accessible Pages deployment.
- GitHub Actions intentionally uses only preinstalled Bash, coreutils, jq and Node, plus Pages Actions. It does not parse Parquet or run Python.
