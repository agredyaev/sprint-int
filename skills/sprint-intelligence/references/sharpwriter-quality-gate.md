# Sharpwriter final publication gate (mandatory)

`sharpwriter` is an **external existing Amazon Quick skill** expected in the user's Quick skills registry; it is not a bundled tool or Python package. Activate by name using the platform's supported skill mechanism and verify that Quick has actually loaded it. Do not invent an MCP tool, local CLI, API or fabricated quality score. Amazon Quick supports naming skills in chat; availability is workspace-specific.

## Sequence

1. Only after `out/quality.json` has `pass=true`, generate `report.md` and the concise `approved-sprint.json` from the selected top epic keys, independently confirmed evidence, operational annex, and coverage.
2. Invoke **skill `sharpwriter`** on the *complete* draft **and the final allowlisted payload**, `highlight_selection.json`, `rollup.json`, `quality.json` and relevant primary source links. Request its **full Quality Gate**, not just rewriting/shortening. This is a mandatory blocker before publication.
3. Have sharpwriter check all of the following:
   - `factual_accuracy`: compare assertions and dates to source (no invented before/after, no unsupported deployment).
   - `evidence_attribution`: each substantive outcome, milestone, risk and quantitative claim has an accurate Jira/Confluence reference.
   - `no_unsupported_value_claims`: do not equate Jira activity with delivered business value; preserve unknowns.
   - `highlight_relevance`: exactly the quality-approved top epics; no routine/manual-only epic elevated by ticket volume.
   - `materiality_and_risks`: verified customer milestones and important internal initiatives are explained sufficiently; blockers accurately represented.
   - `clarity_and_concision`: stakeholder-language, clear before→after, no duplicate narrative, appropriately short.
   - `coverage_and_uncertainty`: all coverage gaps and unverified metrics remain visible.
4. Apply requested corrections, then re-run full sharpwriter gate on the **exact final bytes** of `report.md` **and final payload content**, not an earlier draft. Cap revisions at two attempts before halting and escalating unresolved issues. The sharpwriter result itself must indicate PASS with zero outstanding critical/major issues; this skill cannot assume success just because it was invoked.
5. Record the result as `sharpwriter-receipt.json` *only from an actual invocation*:

```json
{"skill_name":"sharpwriter","status":"pass","report_sha256":"<actual SHA256 of final report.md>","approved_payload_sha256":"<canonical payload SHA256>","quality_sha256":"<canonical quality SHA256>","selection_sha256":"<canonical selection SHA256>","source_sha256":"<quality source_sha256>","checked_at":"2026-10-15T18:00:00+02:00","critical_issues":0,"major_issues":0,"checks":{"factual_accuracy":true,"evidence_attribution":true,"no_unsupported_value_claims":true,"highlight_relevance":true,"materiality_and_risks":true,"clarity_and_concision":true,"coverage_and_uncertainty":true},"revision_rounds":1,"review_reference":"<actual Quick sharpwriter result reference>"}
```

Create and validate the allowlisted `approved-sprint.json` outside Git **before the final sharpwriter invocation and before** calling `publish`. Both report markers and payload highlight ranks must match the exact `quality.highlight_selection`. A Parquet export also requires the generated publication gate and all its checked inputs. See `docs/QUALITY-INTEGRITY.md`.

In the `Executive highlights` section, place one invisible `<!-- HIGHLIGHT_EPIC:DATA-123 -->` marker immediately before each highlighted epic, in selected order; the publication validator checks those markers, not just a self-reported manifest. Save `report-manifest.json` with `report_sha256` and `highlighted_epic_keys` taken *exactly* from `highlight_selection.json`. These hashes make stale receipts detectable, but **do not prove the skill was actually invoked**; the agent must ensure the receipt is grounded in the actual sharpwriter output.

```bash
python scripts/quality_gate.py publish \
  --quality out/quality.json --selection out/highlight_selection.json \
  --report report.md --manifest report-manifest.json \
  --sharpwriter-receipt sharpwriter-receipt.json \
  --payload approved-sprint.json --out out
```

The result is `out/publication_gate.json`. Publish/share the report only when it is `pass=true`. **If sharpwriter is missing, disabled, its result inaccessible, or any check fails, report an unfinished draft and explain the missing gate; never forge a PASS.**
