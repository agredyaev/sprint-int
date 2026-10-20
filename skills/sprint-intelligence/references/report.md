# Final report template — customer value first

Only write stakeholder-facing `report.md` after `out/quality.json` passes. Top highlights are **exactly** `out/highlight_selection.json.selected_epic_keys`; `rollup.json.epics` is an unranked inventory, NOT a ranking. Do not promote an epic because it has many issues, statuses or comments.

# Sprint Intelligence — <project> / <sprint>
**Window:** <start> – <min(end, as_of)> | **As of:** <timestamp> | **Coverage:** <N>/<expected>, histories <N>, data completeness <full/partial>.

## 1. Executive highlights — top customer and strategic internal outcomes
Use up to five epics approved by the highlight-selection gate, in its order. **Before each executive epic write the invisible Markdown comment `<!-- HIGHLIGHT_EPIC:DATA-123 -->` with the real epic key.** The final publication gate verifies the exact selected list and order from these markers. For each give 3–5 factual sentences:
**<Epic and objective> [Customer/Internal]** — what capability or service existed before; what **material milestone changed in this sprint**; what was shipped/merged/tested vs merely progressed; measurable/observable outcome (only if verified); blocker or next gate; Jira/Confluence references. If needed, explicitly say baseline/outcome unclear. Feature delivery, new services, architecture refactoring that materially improves product/platform, tested fixes and strategic internal technical initiatives belong here.

For an epic with genuine progress but no deployed release, describe the actual **verified intermediate milestone** (e.g. integration completed or performance validated); never label it delivered. Keep important active critical-path blocks in `Risks` as well; no duplicate paragraphs.

**Do not include** routine refreshes, spreadsheet reconciliations, manual exports, ad hoc tickets, repeated reruns, ticket grooming, permission changes, administrative work or operations-only epics in executive highlights. Even dozens of `Done` tasks cannot override this exclusion. Verified outage recovery belongs in the reliability/incident section, with a brief executive risk callout only if material to business continuity.

## 2. Additional material initiatives
Compact treatment for other valid product/internal candidates beyond the highlight cap, or material initiatives that lack a validated sprint milestone. Explicitly mark unknown evidence.

## 3. Risks, blockers and decisions
Material risks to customer delivery or internal initiatives, owners/dependencies when available, next decisions. Critical incident recovery may be mentioned here with evidence; do not count it as a shipped feature.

## 4. Operational workload — deliberately outside top highlights
Quantify root tickets: routine/manual support, recurring exports/reconciliations, maintenance, incidents, unknowns. Show denominators, pattern examples and issue references. If hours are unavailable, no estimate of hours consumed; issue counts ≠ capacity. Note candidate workflows for automation but don't shame individuals.

## 5. Automation and AI impact
| Process | Starting mode | Change this sprint | Proposed / piloted / in use / measured | Verified effect | Evidence |

Separate scripts, AI-assisted and AI-automated. No fake savings. Stage and timing supported by source.

## 6. Classification quality and data coverage
State: number of root items reviewed independently / required, reviewer agreement on the reviewed subset (not true accuracy), corrected cases, unresolved disagreements, extraction completeness, changelog coverage, unknown outcomes, baseline availability and any known scope limitation. Include source references. Do not claim validated outcome if evidence absent.

## 7. Publication Quality Gate
After preparing full report, **invoke skill `sharpwriter` and run its entire Quality Gate** per `references/sharpwriter-quality-gate.md`. Incorporate changes, obtain actual PASS receipt tied to final file hash and run `quality_gate.py publish`. Publish only if `out/publication_gate.json.pass=true`; otherwise label output DRAFT — QUALITY GATE NOT PASSED.

## General ranking rules
- One verified customer release is more prominent than a large number of support tickets.
- Verified internal platform improvement/refactoring can be material if the goal and milestone are backed by evidence.
- Repeated customer service requests are not customer *product* delivery unless the service/capability changes.
- Operations still appear in the workload section; do not conceal work or assume all support has zero value.
- Missing baseline means a *current-sprint snapshot with qualified evidence*, not automatically a before/after verified outcome.
