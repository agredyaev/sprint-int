# Sprint data update procedure

This document defines the steps from selecting a Jira sprint to observing its
report on GitHub Pages. The operator is Amazon Quick. The repository is not a
Jira ingestion service and does not schedule or initiate an extraction.

## Preconditions

1. Quick has read access to the correct Atlassian site, board, sprint and
   relevant issue/changelog/epic sources. Confluence access is used for
   directly relevant epic references when available.
2. The Reporting ownership rule is verified. A shared Jira project key does
   not identify team ownership.
3. Quick has a secure temporary workspace **outside the repository**, Python
   execution and DuckDB (or an alternative writer implementing the exact
   physical Parquet contract).
4. Quick can invoke the real `sharpwriter` skill. Without a verifiable complete
   quality-gate PASS, the output remains DRAFT and must not be committed.
5. The intended GitHub Pages audience has explicit permission to access the
   full report data. UI filtering does not restrict Parquet downloads.

## Execution graph

```text
[0] Select ONE sprint and lock ownership/window
                    |
[1] Paginate current sprint membership to exhaustion
                    |
[2] Resolve parents; fetch named epics and focused Confluence context
                    |
[3] Freeze transient source files
                    |
[4] prepare: create bounded, epic-scoped work packets
                    |
                    +-----+-----+-----+
                    |     |     |     |
                  W1    W2    W3    W4     (parallel only if available)
                    |     |     |     |
                    +-----+-----+-----+
                    |
[5] merge-packets: fail on missing/extra/duplicate keys
                    |
[6] independent review + per-epic assessments
                    |
[7] assess: central ranking and evidence/coverage gate
                    |
[8] aggregate: factual metrics and draft data
                    |
[9] final report + compact JSON payload -> sharpwriter full gate
                    |
[10] publish --payload -> verified approval artifact (private)
                    |
[11] Quick: stage sprint + index, validate, create manifest, commit manifest last
                    |
[12] Review both Parquet changes -> commit -> push main
                    |
[13] CI: syntax/structural checks -> stage -> backup -> deploy
                    |
[14] Browser reload -> new index -> selected sprint -> dashboard
```

## 0-3. Build a frozen source universe

- Resolve Jira cloud/site, board, exact sprint ID, actual sprint start/end,
  timezone, `as_of`, the JQL filter and its pagination coverage.
- Page through `sprint = <Jira sprint ID>` until the API reports completion.
  Record counts, failures and duplicates; do not silently omit pages.
- Determine Reporting ownership using team fields or an approved source-backed
  roster. Exclude DWH-owned issues from Reporting delivery. Keep relevant DWH
  issues as separately attributed dependencies only.
- Write `snapshot.json` and `issues.jsonl` in the private run directory. Keep
  the raw source cache private; normalized `issues.jsonl` covers admitted sprint
  members only.
- Resolve each issue's parent/subtask chain. Fetch every distinct referenced
  named epic **separately**, including epics not assigned to this sprint.
  Create `epic_context.jsonl` with goal, full description, acceptance/DoD,
  owner, source references and `context_status`. Unassigned issues use the
  `__NO_EPIC__` analysis group.
- Fetch **all pages of Jira comments for every Reporting sprint issue** (including subtask and in-sprint epic records), not only the comments returned inline by Jira search. Normalize IDs, author references, created/updated timestamps, permalinks, full comment text and per-issue pagination metadata. Keep comments created before the sprint for context, but do not count them as current-sprint progress.
- Fetch relevant issue changelogs and linked Confluence decisions. For parent epics selected as substantive candidates, re-read relevant epic comments and acceptance decisions. Record missing source coverage and baseline limitations.
- Freeze only after verifying `comments_total == len(comments)` and complete pagination for every included issue. If any issue has `comments_complete=false`, the run may produce a DRAFT but `assess`/`publish` cannot approve FINAL.
- Freeze the source inventory before worker classification. Retry targeted
  evidence gaps; do not run competing independent full-sprint scans.

Reference: [extraction.md](../references/extraction.md).

## 4-5. Prepare, classify and merge

All commands in this section run **in Quick's Python execution environment**.
From the root of the skill directory, with `RUN` pointing outside Git:

```sh
cd /path/to/repository/skills/sprint-intelligence
RUN=/secure/quick-runs/REPLACE_RUN_ID

python scripts/sprint_pipeline.py prepare \
  --snapshot "$RUN/snapshot.json" \
  --issues "$RUN/issues.jsonl" \
  --epics "$RUN/epic_context.jsonl" \
  --out "$RUN/out"
```

Outputs: `out/work_packets.jsonl`, `out/issue_features.jsonl`,
`out/coverage.json`. Defaults: at most 12 issue records and 12,000 JSON
characters per packet, including compact epic context. Packet IDs are stable
for a frozen input. Each admitted issue is assigned to exactly one packet.

If Quick supports actual child agents, dispatch 2-4 packets concurrently (not
necessarily four different epics). Give each worker its **own** packet and
allow targeted, read-only evidence retrieval. Otherwise run the same packet
contract sequentially; do not claim parallel execution.

Each worker returns one row in `packet_results.jsonl` with `packet_id`,
`epic_key`, `run_id`, `source_manifest_sha256`, `packet_sha256`, and `classifications[]` for **exactly** the packet's issue keys.
Workers classify current-sprint evidence; they do not emit global metrics,
select final highlights or publish. The orchestrator collects every response
and runs:

```sh
python scripts/sprint_pipeline.py merge-packets \
  --packets "$RUN/out/work_packets.jsonl" \
  --results "$RUN/packet_results.jsonl" \
  --out "$RUN/out"
```

Outputs: `out/classifications.jsonl`, `out/packet_coverage.json`. Missing,
extra, duplicate or wrong-epic results stop the pipeline. Retry failed packets
by their stable IDs; do not merge partial sets.

## 6-9. Review, rank and pass quality gates

The orchestrator creates an independent review plan:

```sh
python scripts/quality_gate.py review-plan \
  --snapshot "$RUN/snapshot.json" \
  --issues "$RUN/issues.jsonl" \
  --classifications "$RUN/out/classifications.jsonl" \
  --out "$RUN/out"
```

Quick must then perform a separate evidence-based review and create
`classification_reviews.jsonl`. Each reviewed record must echo the exact `source_sha256` from `classification_review_plan.json`. Review all mandatory material/delivered/
blocked/ambiguous root issues, incidents and automation changes, plus the
required routine sample. A second pass reading only the first worker's
explanation is not independent review.

After all packets for an epic have merged, create its sourced assessment in
`epic_assessments.jsonl`: `context_sha256` and `source_sha256` from current inputs, objective, actual sprint milestone, evidence, risk,
remaining work and context completeness. Do not use work from other sprints as
this sprint's delivery. The orchestrator alone runs the global selection:

```sh
python scripts/quality_gate.py assess \
  --snapshot "$RUN/snapshot.json" \
  --issues "$RUN/issues.jsonl" \
  --epics "$RUN/epic_context.jsonl" \
  --classifications "$RUN/out/classifications.jsonl" \
  --source-manifest "$RUN/out/source_manifest.json" \
  --packets "$RUN/out/work_packets.jsonl" --packet-results "$RUN/packet_results.jsonl" \
  --plan "$RUN/out/classification_review_plan.json" \
  --reviews "$RUN/classification_reviews.jsonl" \
  --epic-assessments "$RUN/epic_assessments.jsonl" \
  --out "$RUN/out"

python scripts/sprint_pipeline.py aggregate \
  --snapshot "$RUN/snapshot.json" \
  --issues "$RUN/issues.jsonl" \
  --classifications "$RUN/out/classifications.jsonl" \
  --out "$RUN/out"
```

`assess` produces `out/quality.json` and `out/highlight_selection.json`.
The latter's `selected_epic_keys` is the **only** permitted ranked executive
shortlist; `aggregate` produces unranked `out/rollup.json` and a facts-only
`out/report-draft.md`. Do not rank on issue volume, status transitions or
worker preference. Manual-only epics stay out of highlights.

Create final `report.md` following the skill template, with the exact approved
highlight keys marked `<!-- HIGHLIGHT_EPIC:KEY -->` in order. Invoke the
**actual** Quick `sharpwriter` skill for its full seven-check gate on the
complete report. Fix findings, repeat the gate on the **final file bytes**,
produce an actual-source `sharpwriter-receipt.json`, then create
`report-manifest.json` with matching SHA256 and selected keys. **Before the final sharpwriter invocation and before calling `publish`, construct `approved-sprint.json` outside Git.** Its sprint ID and ranked epic keys must agree with the approved selection. This is the payload whose canonical JSON digest is bound to the sharpwriter receipt and publication artifact. Receipt fields: `report_sha256`, `approved_payload_sha256`, `quality_sha256`, `selection_sha256`, `source_sha256`. Generate them from the exact reviewed artifacts after the real sharpwriter invocation; never create a synthetic PASS.

```sh
python scripts/quality_gate.py publish \
  --quality "$RUN/out/quality.json" \
  --selection "$RUN/out/highlight_selection.json" \
  --report "$RUN/report.md" \
  --manifest "$RUN/report-manifest.json" \
  --sharpwriter-receipt "$RUN/sharpwriter-receipt.json" \
  --payload "$RUN/approved-sprint.json" \
  --out "$RUN/out"
```

**Stop unless** `out/quality.json.pass=true` and
`out/publication_gate.json.pass=true`, with an actual `sharpwriter` PASS
corresponding to the current report hash. `quality` fields in the eventual
handoff JSON are not substitutes for these invocations.

## 10-11. Write approved Parquet and rebuild the index

Quick constructs the small allowlisted handoff matching
`examples/quick-payload.json` and writes it **outside Git**, for example
`$RUN/approved-sprint.json`. It contains short approved narrative, selected
Reporting tasks, dependencies and metrics; no raw Jira/Confluence evidence.

From the repository root, in Quick's Python environment with DuckDB available:

```sh
cd /path/to/repository
python skills/sprint-intelligence/scripts/pages/export.py \
  --input "$RUN/approved-sprint.json" \
  --publication-gate "$RUN/out/publication_gate.json" \
  --quality "$RUN/out/quality.json" \
  --selection "$RUN/out/highlight_selection.json" \
  --report "$RUN/report.md" \
  --manifest "$RUN/report-manifest.json" \
  --receipt "$RUN/sharpwriter-receipt.json" \
  --repo /path/to/repository
```

The helper verifies all hash-bound approval inputs and requires
`sprint.schema_version = 2`. It writes the candidate Parquet into a temporary
workspace, rebuilds the complete v2 history index from canonical + candidate
snapshots, reads back all snapshots, and creates `data/manifest.json` containing
the exact ID list, versions, SHA-256 digests and byte lengths. Only after all
checks pass does it move files into place. Existing versions are retained in
scratch storage until the complete publish succeeds; ordinary errors roll back
sprint and index. `manifest.json` is replaced **last**. A terminated process
between file renames can leave a partial set; the stale manifest then causes
CI to reject the publish. Rerun the validated export or `--index-only` before
committing. This helper is **not** invoked by CI.

For a reviewed correction of an existing sprint, repeat extraction/review/
`sharpwriter` and the publication gate for the corrected content, then add
`--replace` **with all approval inputs again**. That flag merely permits overwriting a file. It does not prove
that the correction was reviewed. Never modify Parquet bytes manually.

For recovery **when all canonical sprint files are verified and correct**, but
history or the manifest is missing/stale:

```sh
python skills/sprint-intelligence/scripts/pages/export.py \
  --repo /path/to/repository --index-only
```

The index command validates all canonical files before regenerating the index
**and its manifest**. It refuses an empty or mixed demo/production dataset.
Demo snapshots require `--allow-demo` and must not mix with real reports.

## Schema changes before a new sprint export

A schema change is a **separate reviewed code change**, not an implicit
side-effect of publishing a sprint. Follow the ordered procedure in
[SCHEMA-EVOLUTION.md](SCHEMA-EVOLUTION.md) before step 10:

1. Define field meaning, grain, type, source and null behavior.
2. Classify the change; add nullable fields under a new schema version.
3. Update validator, Quick writer, history projection and browser reader.
4. Test old/new mixed files; leave old Parquet immutable.
5. Complete the normal Quick extraction and quality gates.
6. Stage new snapshot, rebuild nullable index and regenerate the file manifest.
7. Validate read-back and the browser before committing.

GitHub Actions does not migrate schemas or regenerate the history index.

## 12-14. Commit, deploy and read

1. Review the sprint ID, scope, approved narrative and all KPI values against
   the temporary handoff. Because Parquet is binary, a normal Git diff is
   insufficient. Verify with the Quick exporter/read-back checks.
2. Confirm both the new/replaced sprint Parquet and rebuilt history Parquet
   are present and consistent. Stage **only** approved files:

   ```sh
   SPRINT_ID=26.21 # replace with the approved ID
   git add "data/sprints/${SPRINT_ID}.parquet" data/history.parquet data/manifest.json
   git commit -m "Publish sprint ${SPRINT_ID}"
   git push origin main
   ```

3. `.github/workflows/pages.yml` runs after a qualifying push to `main`.
   It uses preinstalled Node to syntax-check `app.js` and `data-store.js`,
   runs static tests and calls `bash ci/stage.sh`.
4. `ci/stage.sh` validates the exact allowlisted site file set and JSON
   manifest shape. It checks Parquet IDs, sizes, SHA-256 and `PAR1` magic
   before staging only `index.html`, three assets, `manifest.json`, history
   and the named sprint files. Extra files or symlinks block publication.
   CI has no Parquet decoder, so this is a **consistency** check, not proof
   of readable Parquet, Jira ownership, or actual `sharpwriter` execution.
5. The workflow archives data as `artifacts/sprint-history.tar.gz`, uploads
   it as an Actions artifact (30-day retention), then deploys `_site/`.
   This archive is not downloaded by the browser.
6. After successful Pages deployment, **reload** the site. The browser first
   fetches `data/manifest.json`, then validates each requested Parquet by
   SHA-256 and size before registering it in DuckDB-Wasm. The history IDs and
   schema versions must match the manifest. Selected sprint details load lazily.
   No browser-side installation.

Documentation-only edits do not automatically redeploy Pages: the workflow's
push path filter excludes `docs/**`. Use `workflow_dispatch` if deployment is
needed without a data/site change.

## Failure and recovery matrix

| Failure | Effect | Required action |
|---|---|---|
| Sprint search pagination incomplete | Unsupported issue universe | Stop FINAL; resume extraction and recheck counts |
| Reporting ownership unresolved | DWH/Reporting counts cannot be trusted | Resolve ownership; rerun affected stages |
| Parent epic context absent | Packet preparation rejects named epic | Fetch epic or mark unavailable; no unsupported highlight |
| Worker packet missing/duplicated | `merge-packets` stops | Retry packet and rerun merge; no partial report |
| Independent review or epic selection fails | `quality.json.pass=false` | Resolve evidence and repeat affected review/assessment |
| `sharpwriter` missing, fails or stale SHA | `publication_gate.json.pass=false` | Keep DRAFT outside Git; repeat full gate |
| Approved payload fails schema checks | Export rejects the payload | Correct handoff, rerun quality checks if content changes |
| Existing sprint without `--replace` | Export refuses overwrite | Use reviewed correction path; do not bypass review |
| Sprint file written, history rebuild fails | Working tree temporarily inconsistent | Repair root cause; run `--index-only`; verify before commit |
| History, sprint or manifest missing at CI | Deployment fails | Revalidate canonical snapshots, rebuild history and manifest in Quick, then commit all changed files |
| CI passes with wrong semantic data | Possible: CI checks hashes, not Parquet structure or source claims | Stop publication upstream; independently validate in Quick |
| Wasm/CDN/Parquet HTTP fetch fails | Browser displays load error | Inspect network/CSP; verify CDN and published URLs |
| Publication contains restricted data | Asset accessible to site visitors | Disable access/deployment; follow incident process; Git revert alone cannot erase copies or history |

## Rollback

The rollback unit is the reviewed **pair** of canonical sprint files and the
history index. Revert the erroneous data commit (or restore known-good file
versions), verify consistency with the Quick exporter, and redeploy through a
new commit. If the original commit contained confidential data, **reverting is
not sufficient**: Git history, downloaded assets and workflow artifacts may
retain copies. Escalate through the organization's data incident procedure.

## Not implemented

- Automated scheduled Jira extraction or unattended Quick runs.
- Server-side access control for individual Parquet records.
- Semantic Parquet validation or sharpwriter execution inside CI.
- Browser auto-refresh when new sprint data arrives.
- Migrator for a future normalized epic/task Parquet schema.

## Implementation integrity

See [QUALITY-INTEGRITY.md](QUALITY-INTEGRITY.md). Static CI checks allowlisted files, manifest hashes/sizes and Parquet magic; it does not parse Parquet. A successful Pages workflow cannot validate the truth of the underlying Jira or Confluence claim, the existence of an external sharpwriter execution, or the DuckDB-Wasm runtime.
