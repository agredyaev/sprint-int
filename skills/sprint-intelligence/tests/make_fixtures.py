"""Generate synthetic, non-sensitive Jira fixtures for local acceptance tests."""
import json
from pathlib import Path
BASE = Path(__file__).resolve().parent
BASE.mkdir(parents=True, exist_ok=True)
SITE = 'https://example.atlassian.net/browse/'
T0 = '2026-10-03T10:00:00+02:00'
T1 = '2026-10-07T10:00:00+02:00'
T2 = '2026-10-10T14:00:00+02:00'

def status_events(n):
    return [{'at': T1, 'field':'description','from':'old','to':'updated', 'url':SITE+'OPS-101'} for _ in range(n)]

def issue(key, title, kind, status, epic=None, parent=None, **extra):
    return {'key':key,'summary':title,'issue_type':kind, 'status':status, 'url':SITE+key,
            'project_key':'OPS', 'created':T0, 'updated':T2,'epic_key':epic,'parent_key':parent,
            'changelog':[],'changelog_complete':True, 'comments':[],
            'comments_complete':True, 'comments_total':0, 'comments_pages':1, **extra}

snap = {'schema_version':'1.0','project_keys':['OPS'],'site_url':'https://example.atlassian.net',
        'board_id':42,'sprint':{'id':101,'name':'Sprint 18','start':'2026-10-05T09:00:00+02:00','end':'2026-10-16T18:00:00+02:00'},
        'as_of':'2026-10-15T18:00:00+02:00','completed_statuses':['Done'],
        'extraction':{'query':'sprint = 101','complete':True,'expected_issues':10,'pages':2,'changelog_complete':True},
        'baseline':{'available':False,'source':None}}
issues = [
    issue('OPS-100','Routine data operations','Epic','In Progress'),
    issue('OPS-101','Manual data refresh for business owner','Task','Done',epic='OPS-100',description='Re-run export, copy report and send it to requester',changelog=status_events(18)),
    issue('OPS-102','Manual reconciliation from spreadsheet','Task','In Progress',epic='OPS-100',description='Reconcile vendor reports by hand',changelog=status_events(12)),
    issue('OPS-200','New reporting capability','Epic','In Progress'),
    issue('OPS-201','Customers can download new report','Story','Done',epic='OPS-200',changelog=[{'at':T2,'field':'status','from':'In Progress','to':'Done','url':SITE+'OPS-201'}]),
    issue('OPS-202','Acceptance-test details','Sub-task','Done',parent='OPS-201',is_subtask=True,changelog=[{'at':T2,'field':'status','from':'In Progress','to':'Done'}]),
    issue('OPS-301','Closed before sprint start; comment during sprint','Bug','Done',changelog=[{'at':T0,'field':'status','from':'In Progress','to':'Done'}],comments=[{'id':'1','created':T2,'body':'Following up',
              'url':SITE+'OPS-301?focusedCommentId=1'}], comments_total=1),
    issue('OPS-400','Proposed scheduler automation','Epic','In Progress'),
    issue('OPS-401','Plan possible automation of monthly exports','Task','To Do',epic='OPS-400',description='Proposal only, no production use'),
    issue('OPS-402','Restore customer-facing batch jobs','Incident','Done',epic='OPS-400',changelog=[{'at':T1,'field':'status','from':'Blocked','to':'Done'}])
]

def c(key, w, m, o, ev=None, cand=None, **extra):
    return {'key':key,'work_type':w,'execution_mode':m,'outcome':o, 'confidence':'high' if ev else 'medium',
            'evidence':ev or [], 'automation_candidate':cand,'customer_impact':None, 'blocker':None, **extra}

evidence = [{'source':'jira','ref':'OPS-201','url':SITE+'OPS-201','fact':'User acceptance confirmed, feature released','at':T2}]
labels = [
    c('OPS-100','operational_support','unknown','in_progress'),
    c('OPS-101','operational_support','manual','completed_unverified',cand=True),
    c('OPS-102','operational_support','manual','no_material_change',cand=True),
    c('OPS-200','product_feature','unknown','in_progress'),
    c('OPS-201','product_feature','unknown','delivered_verified',evidence,False,customer_impact='Users can download reports'),
    c('OPS-202','product_feature','unknown','completed_unverified'),
    c('OPS-301','bug_fix','unknown','no_material_change'),
    c('OPS-400','platform_enablement','unknown','in_progress'),
    c('OPS-401','discovery','unknown','in_progress',cand=True),
    c('OPS-402','incident','unknown','delivered_verified',[{'source':'jira','ref':'OPS-402','url':SITE+'OPS-402','fact':'Service restored','at':T1}])
]

for fname, value in [('sample_snapshot.json',snap)]:
    (BASE/fname).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n', encoding='utf-8')
for fname, rows in [('sample_issues.jsonl',issues),('sample_classifications.jsonl',labels)]:
    (BASE/fname).write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows),encoding='utf-8')
