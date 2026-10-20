# Quality and publication integrity

This document defines deterministic checks implemented by Sprint Intelligence. It does **not** certify that an external reviewer actually inspected Jira or that `sharpwriter` ran. That evidence must come from Amazon Quick's trusted execution record. A JSON receipt is an assertion, not cryptographic authentication.

## Invariants

1. `snapshot.sprint.publication_id` is the canonical published ID (for example `26.21`); it may differ from the Jira numeric `sprint.id`. `quality.sprint_id` and the final payload ID must match this value. `snapshot.run_id` identifies one extraction/review attempt. Store a nonempty value before `prepare`. Changing the source invalidates the attempt.
2. `snapshot.reporting_ownership.provider_issue_keys` must be the exact unique Jira provider sprint membership. It equals the disjoint union of `issues.jsonl` Reporting keys, verified `excluded_other_team_issues[].key`, and `unresolved_issue_keys`. Each exclusion requires a non-Reporting team, source Jira URL, reason and `ownership_verified=true`. `provider_member_count` and `extraction.expected_issues` are the same provider count. Unresolved ownership blocks publication. These fields are **Quick-side attestations**, not independent Jira API signatures. The reviewer must recheck excluded issue ownership against Jira.
3. `issues.jsonl` contains only in-sprint Reporting issues. Resolve external parents before `prepare`. Parent epics outside the sprint appear only in `epic_context.jsonl` and never increment sprint issue counts.
4. Each complete epic context declares `acceptance_status`: `present`, `not_defined_at_source`, or `not_applicable`. `present` requires nonempty `acceptance_criteria`. Other values require `acceptance_reason` from an actual source check. `partial` or `unavailable` cannot be executive highlights.
5. `prepare` writes `source_manifest.json` and bounded `work_packets.jsonl`. Each packet contains `run_id`, `source_manifest_sha256`, and `packet_sha256`. A worker **must echo all three**; `merge-packets` rejects stale results or altered packets. Use targeted primary-source re-reads for truncated evidence and report missing material.
6. `review-plan` creates `source_sha256 = SHA256(canonical JSON of snapshot, issues, classifications)`. Each independent `classification_reviews.jsonl` row must echo `source_sha256`; its referenced evidence must identify the reviewed issue. The assessor **recomputes the review plan**, ignoring the supplied plan for selection, and rejects any mismatch. If a classification changes, regenerate plan and reviews.
7. Each substantive `epic_assessments.jsonl` row contains `context_sha256 = SHA256(canonical epic-context object)` and `source_sha256` from the review plan. Any edit to epic context or classifications invalidates the assessment. The orchestrator ranks high-materiality verified outcomes ahead of medium ones, then verified delivery/blocked/progress state, then customer-vs-internal ties, then stable epic key; operational-only epics are excluded.
8. Produce the **final allowlisted payload** (`approved-sprint.json`) outside Git before invoking `publish`. It must have the same sprint and ordered highlight keys as `quality.json`, `highlight_selection.json`, and the exact `report.md` markers.
9. Run real `sharpwriter` full Quality Gate on the final report **and the final compact payload** and retain its trusted invocation reference. The receipt must bind `report_sha256` (report file bytes), `approved_payload_sha256` (canonical JSON digest), `quality_sha256`, `selection_sha256`, and `source_sha256`. Do not reuse a sharpwriter result after changing any of these inputs. The local gate validates the receipt and report SHA, but cannot authenticate the platform invocation by itself.
10. `publish --payload` writes `publication_gate.json` with hashes for the final payload, report, quality, selection, receipt and frozen source. Export requires the gate **and the original source files**. It recomputes every structural check before writing a canonical Parquet file. This does not authenticate external skill invocations. Editing any input after approval fails the export.
11. `verified_time_saved_hours = null` means unknown/unmeasured; zero is a measured zero. The browser displays an em dash for NULL, never 0. `material_outcomes` counts all independently confirmed material outcomes, not only the selected executive top 5. The payload validator enforces `material_outcomes >= selected highlights`, but evidence confirmation of the full count is the Quick reviewer's responsibility.
12. GitHub Pages CI stages only four static assets and the exact Parquet file set sealed by Quick in `data/manifest.json`; it checks SHA-256, size and Parquet magic, but it does **not** perform semantic Parquet checks. A successful CI run does not imply a successful Quick, Jira, `sharpwriter`, or DuckDB-Wasm end-to-end test. Publication requires separate audience authorization. Assume Parquet files are downloadable by anyone who has access to the deployed URL.

## Transient data and hashes

```text
snapshot.json + issues.jsonl + epic_context.jsonl
  -> prepare -> source_manifest.json + work_packets.jsonl
  -> worker result echoes packet/run/source hashes
  -> merge-packets -> classifications.jsonl
  -> review-plan -> classification_review_plan.json
  -> reviewer result echoes source_sha256
  -> independently verified epic assessments (context_sha256 + source_sha256)
  -> assess -> quality.json + highlight_selection.json
  -> final report.md + allowlisted approved-sprint.json
  -> real sharpwriter result + hash-bound receipt + report-manifest.json
  -> publish --payload -> publication_gate.json
  -> exporter checks ALL approval inputs, stages sprint + history
  -> Quick validates read-back, creates data/manifest.json, commits manifest last
  -> commit -> GitHub Actions manifest staging -> browser hash-verified DuckDB-Wasm
```

All JSONL source exports, review records, approval artifacts and `approved-sprint.json` belong in an access-controlled temporary Quick workspace, **not in Git**.

## Commands (inside Quick workspace)

After extraction and classification, use the commands in `docs/UPDATE-PROCESS.md` through `assess`. Then **construct the final compact payload before the final sharpwriter review and `publish`** and verify that its selected ranks match `highlight_selection.json`.

```sh
cd /path/to/repository/skills/sprint-intelligence
python scripts/quality_gate.py publish \
  --quality "$RUN/out/quality.json" \
  --selection "$RUN/out/highlight_selection.json" \
  --report "$RUN/report.md" \
  --manifest "$RUN/report-manifest.json" \
  --sharpwriter-receipt "$RUN/sharpwriter-receipt.json" \
  --payload "$RUN/approved-sprint.json" \
  --out "$RUN/out"

cd /path/to/repository
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

The exporter checks that each path refers to the **same** approved run and payload. `approved_payload_sha256`, `quality_sha256`, and `selection_sha256` use `sprint_pipeline.fingerprint()` (SHA256 of UTF-8 canonical `json.dumps(sort_keys=True, separators=(',', ':'), ensure_ascii=False)`), not raw file bytes. `report_sha256` uses the exact report file bytes. `--replace` only permits a reviewed correction; it does not waive verification. `--index-only` is permitted only for rebuilding the index from unchanged, previously reviewed Parquet files.

## Required negative regression suite

```sh
python -m unittest discover -s skills/sprint-intelligence/tests -v
node --test tests/site.test.mjs
```

The tests exercise forged review plans, stale reviewers, changed packets, scope reconciliation, unresolved external parents, missing acceptance, NULL hours, approval mismatch and tampered payloads. The two DuckDB tests require DuckDB in the execution environment. A production release also requires a separate actual Quick + Jira + sharpwriter + Parquet + Chromium test; synthetic receipts and regular unit tests are not substitutes.

## When a source changes

- Source Jira/Confluence issue changed: freeze a new run, rebuild the affected packet, re-merge, regenerate review plan and its reviews, redo epic assessments, rerun both gates, write a new approved snapshot.
- Primary classification revised: re-merge and review again; do not replay an old review.
- Epic objective/acceptance modified: recalculate `context_sha256`, redo the epic assessment and downstream approvals.
- Narrative/payload edited after the sharpwriter pass: repeat the relevant review and full `sharpwriter` gate. Rebuild the publication artifact.
- Previously published sprint corrected: full renewed review, explicit `--replace`, history rebuild, and separate Git commit.

## Known limitations

- The v2 Parquet snapshot has typed scalar metrics but an opaque `report_json` column for nested epics/tasks. A normalized v3 requires its own explicit schema migration and tests.
- External skill invocation and Jira evidence truth cannot be authenticated by local JSON validators. Quick must retain independent trusted evidence and human-readable execution audit outside Git.
- DuckDB-Wasm is currently imported from an externally hosted pinned-version CDN. Browser availability and Content Security Policy have to be tested under the target deployment environment; vendoring is a separate supply-chain decision.
- Site staging checks the allowlist, manifest SHA-256/size and Parquet magic; it does not decode the file or verify the source identity. Never interpret a successful `stage.sh` result as semantic approval.
