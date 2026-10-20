# Remediation of ten-lens review (2026-10-18)

Baseline: `VALIDATION-REPORT.md`, ten criterion-based passes, with seven reproduced negative conditions. This repair modifies code, tests, and the Quick handoff. It does not assert ten independent agent executions.

## Result by finding

| ID | Change | Verification | Remaining constraint |
|---|---|---|---|
| F01 | Recompute the entire classification review plan from current sprint, issues and labels during `assess`; reviewers echo source digest | Forged empty plan and stale reviewer unit tests | A local hash does not prove reviewer independence |
| F02 | Compare the exact ordered selection and full selection object with approved `quality.highlight_selection`; check report markers and payload ranks | Negative altered selection test | Approved reports still depend on upstream semantic truth |
| F03 | `publish` requires the allowlisted payload; sharpwriter receipt is bound to report bytes, canonical payload, quality, selection and source hashes. Export recomputes the gate and refuses bare `passed` flags | Negative missing gate, changed payload and CLI tests | The external sharpwriter invocation must be verified by Quick's trusted execution record |
| F04 | Reconcile provider count against Reporting-admitted plus DWH/other excluded keys | Mixed-team extraction fixture | Ownership rule provenance remains supplied by Quick/Jira |
| F05 | Bind run ID, source manifest and packet digests to worker results; bind reviewers and epic assessments to frozen inputs | Stale run, packet and reviewer tests | Source freshness is established at extraction; no live Jira checks in local validators |
| F06 | `complete` epic requires explicitly examined acceptance status and applicable justification | Missing acceptance tests | Accuracy of source-inspection statements requires reviewer evidence |
| F07 | Unresolved/cyclic parent chains fail rather than being relabelled `__NO_EPIC__` | External parent regression | Quick must fetch parent outside sprint and resolve chain before `prepare` |
| F08 | Nullable time saved preserved in schema, history and browser; no zero coercion | Python and JS contract checks | Real browser + DuckDB-Wasm round-trip still pending |
| F09 | Not claimed fixed | DuckDB integration tests remain skipped when engine absent | Real Parquet v1/v2, full Quick and Chromium execution required |
| F10 | Global comparator uses materiality, milestone state, scope tie-break, key | Customer-medium vs internal-high ranking test | Human materiality judgement remains external |
| F11 | Issue and epic truncation flags exposed, source counts recorded, reread required by instructions | Truncation regression | Re-read activity requires actual Quick source access |
| F12 | Existing `report_json` limitation preserved and documented | Existing versioned schema tests | Normalized task/epic Parquet requires an explicit v3 migration |
| F13 | Audience authorization explicitly required; CI limitation documented | Documentation/manual gate | GitHub Pages URLs and Parquet assets are accessible according to deployment policy |
| F14 | Metric defined as all confirmed material outcomes, separate from selected top 5; validator enforces lower bound | Payload contract validation | Full evidence-based numerator remains a Quick semantic verification task |
| F15 | Pinned external DuckDB-Wasm CDN and CSP dependency documented | JS static checks | Vendoring and target-network/browser verification not implemented |
| F16 | Review evidence must identify the issue, not just an unrelated URL | Wrong-issue source reference test | Source meaning and truth require independent reviewer |

## Required production validation

1. Run against one known Jira sprint with shared Reporting/DWH ownership and out-of-sprint epic parents.
2. Inspect complete Jira/Confluence sources, check acceptance criteria and capture exclusions.
3. Run multiple actual Quick workers if available; verify frozen packet digests and independent reviewer source checks.
4. Verify an actual `sharpwriter` Quality Gate with trusted platform evidence for both final Markdown and compact payload. The local receipt cannot authenticate the invocation.
5. Generate real v1/v2 Parquet, rebuild the history index, and perform a DuckDB readback.
6. Serve the staged site in Chromium, exercise DuckDB-Wasm, NULL metrics, selected sprint loading and both themes.
7. Obtain explicit authorization for the published audience. Treat static Pages files as downloadable.
8. Only after the above may the report be considered ready for unattended production publication.

## Test commands

```sh
python -m unittest discover -s skills/sprint-intelligence/tests -v
node --test tests/site.test.mjs
bash -n ci/stage.sh
node --check site/assets/app.js
node --check site/assets/data-store.js
```

Python executes inside Amazon Quick or local test environments. No Python, Go or `uv` installation occurs in GitHub Pages CI.
