# Minimal decision tree — apply per root work item

Classify from dated changes inside the sprint window. Ignore ticket counts when determining outcomes. Use `classification.md` for edge cases.

```text
A. What verifiable change occurred within the sprint?
   ├─ Confirmed delivery/acceptance/reliability outcome → outcome=delivered_verified
   ├─ Documented intermediate step → outcome=in_progress
   ├─ Explicit active impediment → outcome=blocked
   ├─ Closure/status only, missing acceptance → outcome=completed_unverified
   ├─ Changelog complete; only routine edits → outcome=no_material_change
   └─ Missing history or conflicting claims → outcome=unknown

B. What is the nature of the work? (independent of A)
   ├─ New user-facing or consumer-facing capability → product_feature/enhancement
   ├─ Defect fixed → bug_fix
   ├─ Recovery of outage or urgent incident → incident
   ├─ Repeatable request / rerun / refresh / extract / reconciliation → operational_support
   ├─ Preventive upkeep → maintenance
   ├─ Platform capability, security, reliability, CI/CD → platform_enablement
   ├─ Verified architecture redesign/refactor/performance improvement → engineering_improvement
   ├─ Investigation without delivered change → discovery
   ├─ Coordination/administration → administrative
   └─ Insufficient evidence → unknown

C. How is the task actually executed? (independent of A/B)
   ├─ Procedure performed by people → manual
   ├─ Running script, scheduler, CI automation → scripted_automation
   ├─ Human uses AI in a documented step → ai_assisted
   ├─ AI executes documented operational process → ai_automated
   ├─ Multiple explicitly documented methods → mixed
   └─ Unstated method → unknown

D. Is it repeated, procedural and safely automatable?
   ├─ Yes, repeatability/input/output/controls evidenced → automation_candidate=true
   ├─ Unclear → automation_candidate=null and document evidence gaps
   └─ No → automation_candidate=false

E. Did an AI/automation initiative itself advance this sprint?
   ├─ Proposed only → proposed (not adoption)
   ├─ Piloted with evidence → piloted (not production)
   ├─ Activated with dated evidence → in_use (count as implemented change)
   ├─ Activated AND verified before/after metrics → measured (count measurable change)
   └─ No evidence of an initiative → automation_change=null
```

## Epic synthesis (after local aggregation)

1. State epic goal from Jira epic/linked Confluence page, or `goal_unknown`.
2. Compare starting vs current state **only if changelog or baseline supports it**.
3. Flag incident recovery under reliability/risks, not as shipped feature. Executive highlights are product and strategic internal milestones verified in-sprint.
4. Independently quantify operational burden, manual recurring work, automation/AI adoption and proposals.
5. High ticket count without evidence of a milestone → mark progress unverified; do not infer zero value.
6. No verified advancement → include epic in compact section; do not silently drop it.
