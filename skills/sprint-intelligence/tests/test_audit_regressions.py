"""Negative contract tests. Synthetic approvals validate structure, not real skill execution."""
import argparse
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / 'scripts'
REPO = HERE.parents[2]
sys.path[:0] = [str(SCRIPTS), str(SCRIPTS/'pages')]
import sprint_pipeline as sp
import quality_gate as qg
import export
from validate_report import validate


class AuditRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = sp.read_json(str(HERE/'sample_snapshot.json'))
        cls.issues = sp.read_jsonl(str(HERE/'sample_issues.jsonl'))
        cls.labels = sp.read_jsonl(str(HERE/'sample_classifications.jsonl'))
        cls.epics = sp.read_jsonl(str(HERE/'sample_epic_context.jsonl'))
        cls.payload = json.loads((REPO/'examples/quick-payload.json').read_text())

    def test_f01_modified_review_plan_rejected_even_without_delivery(self):
        labels = copy.deepcopy(self.labels)
        for row in labels:
            if row['outcome'] == 'delivered_verified':
                row['outcome'] = 'in_progress'
        plan = qg.make_plan(self.snapshot, self.issues, labels)
        self.assertTrue(plan['review_issue_keys'])
        forged = {**plan, 'review_issue_keys': [], 'mandatory_keys': [], 'review_reasons': {},
                  'routine_sample_size': 0, 'routine_pool_size': 0}
        result = qg.audit_reviews(self.snapshot, self.issues, labels, forged, [])
        self.assertFalse(result['pass'])
        self.assertTrue(any('recomputed' in x for x in result['problems']))

    def test_f01_review_result_from_old_input_rejected(self):
        plan = qg.make_plan(self.snapshot, self.issues, self.labels)
        rows = []
        lm = {x['key']: x for x in self.labels}
        for key in plan['review_issue_keys']:
            rows.append({'key':key,'verdict':'agree','source_checked':True,
                         'source_sha256':'0'*64,
                         'reviewed_labels':{k:lm[key][k] for k in ('work_type','execution_mode','outcome')},
                         'evidence_checked':[{'fact':'Tested','url':'https://example.atlassian.net/browse/'+key}],
                         'review_note':'Synthetic reference check'})
        out=qg.audit_reviews(self.snapshot,self.issues,self.labels,plan,rows)
        self.assertFalse(out['pass'])
        self.assertIn('source_sha256',str(out['problems']))

    def test_f04_excluded_dwh_does_not_break_count(self):
        snapshot=copy.deepcopy(self.snapshot)
        snapshot['reporting_ownership']['provider_member_count']=2
        snapshot['reporting_ownership']['provider_issue_keys']=[self.issues[0]['key'],'DWH-999']
        snapshot['reporting_ownership']['excluded_other_team_issues']=[{
            'key':'DWH-999','team':'DWH','source_ref':'https://example.atlassian.net/browse/DWH-999',
            'reason':'Jira Team field confirmed in source','ownership_verified':True}]
        snapshot['extraction']['expected_issues']=2
        result=sp.coverage(snapshot,[self.issues[0]])
        self.assertTrue(result['coverage_complete'],result['warnings'])
        self.assertEqual(result['provider_reconciled'],2)
        snapshot['reporting_ownership']['unresolved_issue_keys']=['OPS-999']
        self.assertFalse(sp.coverage(snapshot,[self.issues[0]])['coverage_complete'])

    def test_f05_packet_and_worker_content_addressed(self):
        start,end=sp.window(self.snapshot)
        bykey=sp.indexes(self.issues)
        features=[sp.feature(x,sp.root_epic(x,bykey),start,end) for x in self.issues]
        contexts=sp.epic_context_index(self.epics,{'OPS-100','OPS-200','OPS-400'})
        packets=sp.packetize(features,2,12000,contexts,'a'*64,'run-1')
        results=[{'packet_id':p['packet_id'],'epic_key':p['epic_key'],
                  'packet_sha256':p['packet_sha256'], 'source_manifest_sha256':p['source_manifest_sha256'],
                  'run_id':p['run_id'], 'classifications':[{'key':k} for k in p['source_issue_keys']]}
                 for p in packets]
        self.assertEqual(len(sp.merge_packet_results(packets,results)[0]),len(self.issues))
        modified=copy.deepcopy(results);modified[0]['packet_sha256']='b'*64
        with self.assertRaisesRegex(ValueError,'packet_sha256'):
            sp.merge_packet_results(packets,modified)
        stale=copy.deepcopy(packets);stale[0]['issues'][0]['summary']='changed source'
        with self.assertRaisesRegex(ValueError,'prepared packet bytes'):
            sp.merge_packet_results(stale,results)
        old=copy.deepcopy(results);old[0]['run_id']='previous-run'
        with self.assertRaisesRegex(ValueError,'run_id'):
            sp.merge_packet_results(packets,old)

    def test_f06_acceptance_must_be_examined(self):
        row=copy.deepcopy(self.epics[0]);row.pop('acceptance_status')
        with self.assertRaisesRegex(ValueError,'acceptance_status'):
            sp.epic_context_index([row],{'OPS-100'})
        row['acceptance_status']='present';row.pop('acceptance_criteria')
        with self.assertRaisesRegex(ValueError,'acceptance_criteria'):
            sp.epic_context_index([row],{'OPS-100'})
        row['acceptance_status']='not_defined_at_source';row['acceptance_reason']='Checked Jira fields'
        self.assertEqual(sp.epic_context_index([row],{'OPS-100'})['OPS-100']['context_status'],'complete')

    def test_f07_external_parent_gap_is_not_no_epic(self):
        issue={'key':'OPS-900','parent_key':'OPS-899','issue_type':'Sub-task'}
        with self.assertRaisesRegex(ValueError,'unresolved external parent'):
            sp.root_epic(issue,{'OPS-900':issue})
        self.assertEqual(sp.root_epic({'key':'OPS-901','issue_type':'Bug'},{}),sp.NO_EPIC)

    def test_f10_materiality_precedes_customer_tie_break(self):
        start, end = sp.window(self.snapshot)
        at = start.isoformat()
        issues = [
            {'key':'OPS-711','issue_type':'Story','epic_key':'OPS-710'},
            {'key':'OPS-721','issue_type':'Story','epic_key':'OPS-720'},
        ]
        labels = []
        assessments = []
        contexts = {}
        for issue, scope, materiality in zip(issues, ('customer','internal'), ('medium','high')):
            key=issue['key']; ep=issue['epic_key']
            ev=[{'fact':'Synthetic accepted release','at':at,
                 'url':f'https://example.atlassian.net/browse/{key}','ref':key}]
            labels.append({'key':key,'work_type':'product_feature','execution_mode':'manual',
                           'outcome':'delivered_verified','confidence':'high','evidence':ev,
                           'automation_candidate':False})
            ctx={'epic_key':ep,'context_status':'complete','summary':'Synthetic',
                 'goal':'Deliver approved capability',
                 'acceptance_status':'present','acceptance_criteria':'Production sign-off',
                 'url':f'https://example.atlassian.net/browse/{ep}',
                 'source_refs':[{'ref':ep}]}
            contexts[ep]=ctx
            assessments.append({'epic_key':ep,'initiative_scope':scope,'goal':'Approved capability',
                                'milestone':'Verified delivery','milestone_state':'delivered_verified',
                                'materiality':materiality,'risk_level':'none',
                                'source_checked':True,'context_sha256':sp.fingerprint(ctx),
                                'evidence':ev})
        r=qg.evaluate_epics(self.snapshot,issues,labels,assessments,contexts=contexts)
        self.assertTrue(r['pass'],r['problems'])
        self.assertEqual(r['selected_epic_keys'],['OPS-720','OPS-710'])

    def test_f11_truncated_excerpts_are_flagged_for_source_reread(self):
        start,end=sp.window(self.snapshot)
        issue=copy.deepcopy(self.issues[4])
        issue['description']='x'*1400
        issue['comments']=[{'created':start.isoformat(),'body':'a'*900,'url':'https://example.atlassian.net/browse/OPS-201'}]
        row=sp.feature(issue,'OPS-200',start,end)
        self.assertTrue(row['evidence_truncated'])
        self.assertEqual(row['in_window_comment_count'],1)
        self.assertEqual(len(row['in_window_comments'][0]['text']),len('a'*650+'… [truncated]'))
        epic=copy.deepcopy(self.epics[1]);epic['description']='a'*2300
        c=sp.compact_epic_context(epic,3500)
        self.assertIn('description',c['context_truncated_fields'])

    def test_f16_review_reference_must_identify_own_issue(self):
        self.assertFalse(qg.evidence_points_to_issue([{'url':'https://example.atlassian.net/browse/OPS-999'}],'OPS-201'))
        self.assertTrue(qg.evidence_points_to_issue([{'ref':'OPS-201'}],'OPS-201'))

    def test_f08_unmeasured_time_preserves_null(self):
        doc=copy.deepcopy(self.payload)
        doc['metrics']['verified_time_saved_hours']=None
        self.assertIs(validate(doc),doc)
        doc['metrics']['verified_time_saved_hours']=0
        self.assertIs(validate(doc),doc)

    def fixture(self, root):
        payload=copy.deepcopy(self.payload)
        approved=[e['jira_key'] for e in sorted(payload['epics'],key=lambda x:x.get('highlight_rank') or 99)
                  if e.get('highlight_rank') is not None]
        selection={'pass':True,'selected_epic_keys':approved,'decisions':[]}
        quality={'pass':True,'classification_review':{'pass':True},'highlight_selection':selection,
                 'coverage':{'coverage_complete':True},'worker_fan_in':{'pass':True},'source_sha256':'a'*64,
                 'epic_context_sha256':'b'*64,'sprint_id':payload['sprint']['id']}
        report=root/'report.md'
        report.write_text('## Executive highlights\n'+''.join(f'<!-- HIGHLIGHT_EPIC:{k} -->\n' for k in approved))
        sha=hashlib.sha256(report.read_bytes()).hexdigest()
        manifest={'report_sha256':sha,'highlighted_epic_keys':approved}
        receipt={'skill_name':'sharpwriter','status':'pass','report_sha256':sha,
                 'checked_at':'2026-10-18T12:00:00Z','review_reference':'SYNTHETIC-TEST-NOT-REAL',
                 'critical_issues':0,'major_issues':0,'checks':{k:True for k in qg.CHECKS},
                 'approved_payload_sha256':sp.fingerprint(payload),
                 'quality_sha256':sp.fingerprint(quality),
                 'selection_sha256':sp.fingerprint(selection),
                 'source_sha256':quality['source_sha256']}
        gate=qg.publication_check(quality,selection,receipt,manifest,report,payload)
        self.assertTrue(gate['pass'],gate['problems'])
        objects={'quality':quality,'selection':selection,'receipt':receipt,'manifest':manifest,
                 'publication_gate':gate}
        for name,value in objects.items():
            sp.write_json(root/(name+'.json'),value)
        return payload,quality,selection,receipt,manifest,report,gate

    def test_f02_publication_selected_order_bound_to_quality(self):
        with tempfile.TemporaryDirectory() as d:
            payload,quality,selection,receipt,manifest,report,_=self.fixture(Path(d))
            wrong=copy.deepcopy(selection);wrong['selected_epic_keys']=['OPS-999']
            manifest['highlighted_epic_keys']=['OPS-999']
            result=qg.publication_check(quality,wrong,receipt,manifest,report,payload)
            self.assertFalse(result['pass'])
            self.assertIn('quality-approved',str(result['problems']))

    def test_f03_export_requires_bound_gate_not_flags(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            payload,quality,selection,receipt,manifest,report,gate=self.fixture(root)
            args=argparse.Namespace(publication_gate=None,quality=None,selection=None,
                                    report=None,receipt=None,manifest=None)
            with self.assertRaisesRegex(ValueError,'Export requires'):
                export.verify_approval(payload,args)
            args=argparse.Namespace(**{k:root/(k+'.json') for k in ('publication_gate','quality','selection','receipt','manifest')},report=report)
            export.verify_approval(payload,args)
            altered=copy.deepcopy(payload);altered['sprint']['executive_summary']='After approval changed'
            with self.assertRaisesRegex(ValueError,'stale'):
                export.verify_approval(altered,args)
            altered=copy.deepcopy(gate);altered['selected_epics']=['OPS-999']
            sp.write_json(root/'publication_gate.json',altered)
            with self.assertRaisesRegex(ValueError,'stale'):
                export.verify_approval(payload,args)

    def test_publish_cli_checks_payload_and_writes_bound_gate(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            payload,quality,selection,receipt,manifest,report,gate=self.fixture(root)
            sp.write_json(root/'payload.json',payload)
            args=[sys.executable,str(SCRIPTS/'quality_gate.py'),'publish',
                  '--quality',str(root/'quality.json'),
                  '--selection',str(root/'selection.json'),
                  '--report',str(report),
                  '--manifest',str(root/'manifest.json'),
                  '--sharpwriter-receipt',str(root/'receipt.json'),
                  '--payload',str(root/'payload.json'),
                  '--out',str(root)]
            result=subprocess.run(args,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(sp.read_json(str(root/'publication_gate.json')),gate)
            payload['epics'][0]['delivered']='Changed narrative after approval'
            sp.write_json(root/'payload.json',payload)
            # The old sharpwriter result is stale for the changed payload.
            second=subprocess.run(args,capture_output=True,text=True)
            self.assertEqual(second.returncode,4,second.stderr)
            self.assertFalse(sp.read_json(str(root/'publication_gate.json'))['pass'])

    def test_null_vs_unknown_is_not_zero_in_ui(self):
        ui=(REPO/'site/assets/app.js').read_text()
        ds=(REPO/'site/assets/data-store.js').read_text()
        self.assertIn("x == null ? '—'",ui)
        self.assertIn('numericValue(value[k], k)', ds)
        self.assertIn("if (value == null)", ds)


if __name__ == '__main__':
    unittest.main()
