# Independent classification review and epic highlight selection (mandatory)

## Gate scope
Run after classification and before highlighting epics. Jira activity does not prove delivery. Python determines review coverage and eligibility; the Quick reviewer verifies claims against Jira/Confluence.

## 1. Independent classification verification

1. Generate a stable review sample:

```bash
python scripts/quality_gate.py review-plan --snapshot snapshot.json --issues issues.jsonl --classifications out/classifications.jsonl --out out
```

2. Read `out/classification_review_plan.json`. Review 100% of root issues that could affect highlights: feature/product, substantial platform or refactor, verified delivery, blocked issues, automation changes, incidents and ambiguous labels. Also examine a stable ~25% sample (minimum 3 if available) of other routine tickets. Subtasks are evidence of the parent, not independent root outcomes.
3. **Independent verification:** use a second agent with primary Jira/Confluence evidence. If no second agent is available, conduct an isolated pass against raw sources **without exposing first-pass classifications**. Compare the results afterwards. Verification includes re-reading relevant raw issue/linked evidence, outcome timing, process/work_type, automation actuality, and whether an in-progress milestone is a genuine change.
4. Produce `classification_reviews.jsonl` with one reviewer record for every `review_issue_key`. Required:

```json
{"key":"DATA-123","verdict":"agree","source_sha256":"<classification_review_plan.source_sha256>","source_checked":true,"reviewed_labels":{"work_type":"engineering_improvement","execution_mode":"unknown","outcome":"delivered_verified"},"evidence_checked":[{"source":"jira","ref":"DATA-123","url":"https://example.atlassian.net/browse/DATA-123","fact":"Before/after perf test and merged refactor observed","at":"2026-10-12T13:30:00+02:00"}],"review_note":"Refactoring changed the data service; no evidence of AI execution."}
```

If disagreement or unsupported claims arise, `verdict` must be `corrected` or `insufficient_evidence`. Fix the primary `classifications.jsonl`, regenerate the plan, and independently review the corrected items. **Never silently override classifications downstream.** Preserve original/reviewer disagreement in audit logs.
5. `quality_gate.py assess` checks required review coverage, source references, label agreement and in-sprint evidence for `delivered_verified`. Code checks *structural consistency*; reviewer checks whether the source actually proves the stated fact. Report reviewer agreement, selected denominator, and sampling method. **Do not label this as model classification accuracy** unless separately annotated human/reference gold labels exist. For human-labelled audit sets, supply optional `--gold gold_labels.jsonl` to `quality_gate.py assess` to compute per-axis **reference-set accuracy** and label confusion, and block unresolved gold disagreements. Human reference format: `{"key":"DATA-123","work_type":"...","execution_mode":"...","outcome":"...","human_verified":true,"reviewer_id":"<actual reviewer>","source_ref":"<real Jira URL or key>"}`. Never generate those labels using the same classification model and call them gold. A purposive reference set does not establish accuracy on the entire sprint.

### Frequent false positives to challenge
- Repeated refresh/extract/grant-access -> feature delivered (false; typically operational support).
- `Done` ticket -> customer value delivered (false unless accepted/deployed/verified change).
- A refactor mentioned in a description -> verified architecture improvement (requires change/test/merge evidence).
- AI suggested for automation -> implemented AI impact (false).
- New tickets under an epic -> progress toward epic goal (not proven).
- `manual` feature development -> repeated manual operations (false; two independent dimensions).
- High ticket count -> high business impact (false).
- Infrastructure, incidents or compliance -> automatically "zero value" (false; material risks may be high priority in appropriate section).

Before epic assessment, require the full transient `epic_context.jsonl` for all named epics, fetched separately from sprint membership. Every *substantive* epic needs `context_status=complete` to pass highlight selection; re-fetch a missing goal/acceptance instead of guessing from task labels. `quality_gate.py assess` enforces this with `--epics`. A DWH-owned epic is a dependency, never a Reporting executive highlight.

## 2. Explicit epic assessment

For **every epic with substantive product/engineering root work** (including `__NO_EPIC__` if substantive root items exist), check Jira epic goal, linked scope/acceptance and selective Confluence source. Write `epic_assessments.jsonl` using:

```json
{"epic_key":"DATA-100","initiative_scope":"customer","goal":"Enable customer-owned report exports","milestone":"Report export released and accepted in sprint","milestone_state":"delivered_verified","materiality":"high","risk_level":"none","source_checked":true,"evidence":[{"source":"jira","ref":"DATA-123","url":"https://example.atlassian.net/browse/DATA-123","fact":"Release and acceptance evidence","at":"2026-10-12T13:30:00+02:00"}]}
```

Permitted `initiative_scope`: `customer`, `internal`, `operations`, `unknown`. `milestone_state`: `delivered_verified`, `progress_verified`, `blocked`, `unverified`, `none`. `materiality`: `high`, `medium`, `low`, `unknown`. `risk_level`: `critical`, `high`, `medium`, `low`, `none`, `unknown`. Context-only documents can be older; **evidence that a milestone moved during the sprint must have a dated in-window source**. `source_checked=true` means the agent actually inspected supporting evidence, not inferred a goal from the title.

Judge scope from the *purpose and beneficiaries*, not from project ownership. A workstream for customer data delivery is `customer`; a test harness, service reliability redesign or architectural refactor with a clear team-wide outcome is `internal`; repetitive operational processing remains `operations`, even if a customer submitted the request.

## 3. Non-negotiable highlight decision tree

```text
Do the root issues contain substantive delivery work?
  NO: all routine manual support/admin/maintenance -> NEVER executive highlight;
      account in operational workload and automation opportunities only.
  NO: incidents/recovery plus routine -> reliability/incident section;
      exceptional critical risk can be mentioned in executive risk sentence, not as feature delivery.
  YES: feature / enhancement / verified fix / platform / engineering improvement
    Does the epic deliver a customer capability or a documented internal engineering milestone?
      NO/UNKNOWN -> investigate goal, otherwise appendix/coverage.
      YES: Is there an evidence-backed in-sprint milestone or active critical-path blocker?
        NO -> no main highlight, still record status in appendix.
        YES: Is materiality high/medium, supported by reasons and primary evidence?
          NO -> appendix; not a top highlight.
          YES -> eligible top candidate.
```

Sort by materiality (high before medium), then milestone evidence/state (verified delivered, blocked, progressing), then customer before internal **only on equal preceding factors**, then epic key. The orchestrator must use this order unchanged. Default limit: 5 top epics; other material initiatives in a separate concise section. Ticket count/activity does **not** break ties. Risks that jeopardize critical commitments appear separately even if they are not among top five.

An individual service request is operational support. A verified reusable self-service capability is a product enhancement.

## 4. Run the gate

```bash
python scripts/quality_gate.py assess \
  --snapshot snapshot.json --issues issues.jsonl --epics epic_context.jsonl \
  --classifications out/classifications.jsonl \
  --plan out/classification_review_plan.json \
  --reviews classification_reviews.jsonl \
  --epic-assessments epic_assessments.jsonl --out out
```

Outputs `out/quality.json` (including `pass`/blockers, audit coverage and issues) and `out/highlight_selection.json` (selected keys, sorted inclusion/exclusion reasons, scope and evidence).

If FAIL, correct source/labels/assessment, then rerun. **Do not generate a "final" stakeholder summary from an incomplete gate.** A draft with explicit caveat is allowed. `rollup.json`'s `epics` collection is the complete unranked inventory; only `highlight_selection.json` authorizes the executive highlights.
