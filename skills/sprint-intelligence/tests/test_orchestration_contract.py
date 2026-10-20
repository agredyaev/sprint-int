"""Regression checks for epic-context fetching and fail-closed packet orchestration."""
import json
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import sprint_pipeline as sp  # noqa: E402
import quality_gate as qg  # noqa: E402


class OrchestrationContractTests(unittest.TestCase):
    def setUp(self):
        self.issues = sp.read_jsonl(str(HERE/'sample_issues.jsonl'))
        self.contexts = sp.read_jsonl(str(HERE/'sample_epic_context.jsonl'))
        self.snapshot = sp.read_json(str(HERE/'sample_snapshot.json'))
        self.context_map = sp.epic_context_index(self.contexts, {'OPS-100','OPS-200','OPS-400'})
        start, end = sp.window(self.snapshot)
        bykey = sp.indexes(self.issues)
        self.features = [sp.feature(issue, sp.root_epic(issue, bykey), start, end)
                         for issue in self.issues]

    def test_per_epic_packet_includes_goal_source_and_hard_budget(self):
        packets = sp.packetize(self.features, 2, 4000, self.context_map)
        self.assertEqual(sorted(k for p in packets for k in p['source_issue_keys']),
                         sorted(i['key'] for i in self.issues))
        for packet in packets:
            self.assertLessEqual(len(packet['issues']),2)
            self.assertLessEqual(len(json.dumps(packet,ensure_ascii=False)),4000)
            self.assertIn('epic_context',packet)
            self.assertEqual(packet['epic_context']['epic_key'],packet['epic_key'])
            if packet['epic_key'] != sp.NO_EPIC:
                self.assertTrue(packet['epic_context']['goal'])
                self.assertTrue(packet['epic_context']['source_refs'])
        self.assertGreater(len([p for p in packets if p['epic_key']=='OPS-100']),1)

    def test_missing_duplicate_or_unavailable_context_explicit(self):
        with self.assertRaisesRegex(ValueError,'missing epic_context'):
            sp.epic_context_index(self.contexts[:-1], {'OPS-100','OPS-200','OPS-400'})
        with self.assertRaisesRegex(ValueError,'duplicate epic context'):
            sp.epic_context_index(self.contexts+self.contexts[:1], {'OPS-100','OPS-200','OPS-400'})
        ctx = dict(self.contexts[0],context_status='unavailable')
        ctx.pop('reason_missing', None)
        with self.assertRaisesRegex(ValueError,'reason_missing'):
            sp.epic_context_index([ctx]+self.contexts[1:], {'OPS-100','OPS-200','OPS-400'})

    def test_out_of_sprint_epic_context_never_increases_issue_counts(self):
        issues = [dict(self.issues[4],key='OPS-901',epic_key='OPS-900',parent_key=None)]
        bykey=sp.indexes(issues)
        feats=[sp.feature(i,sp.root_epic(i,bykey),*sp.window(self.snapshot)) for i in issues]
        outside={'epic_key':'OPS-900','summary':'Parent outside sprint','goal':'Long-running plan',
                 'context_status':'complete','url':'https://example.atlassian.net/browse/OPS-900',
                 'source_refs':[{'url':'https://example.atlassian.net/browse/OPS-900'}],
                 'acceptance_status':'not_defined_at_source','acceptance_reason':'Checked issue fields; no AC defined'}
        contexts=sp.epic_context_index([outside],{'OPS-900'})
        packet=sp.packetize(feats,12,12000,contexts)[0]
        self.assertEqual(packet['epic_context']['epic_key'],'OPS-900')
        self.assertEqual(packet['source_issue_keys'],['OPS-901'])

    def test_parallel_fan_in_rejects_missing_extra_or_duplicate_issue(self):
        packets=sp.packetize(self.features,2,12000,self.context_map)
        results=[]
        for p in packets:
            results.append({'packet_id':p['packet_id'],'epic_key':p['epic_key'],
                            'packet_sha256':p['packet_sha256'],
                            'classifications':[{'key':key} for key in p['source_issue_keys']]})
        rows, cov=sp.merge_packet_results(packets,list(reversed(results)))
        self.assertTrue(cov['all_packets_covered'])
        self.assertEqual(len(rows),len(self.issues))
        with self.assertRaisesRegex(ValueError,'missing worker packet'):
            sp.merge_packet_results(packets,results[:-1])
        with self.assertRaisesRegex(ValueError,'unknown or duplicate'):
            sp.merge_packet_results(packets,results+[results[0]])
        damaged=json.loads(json.dumps(results));damaged[0]['classifications'].append({'key':'OPS-999'})
        with self.assertRaisesRegex(ValueError,'issue keys differ'):
            sp.merge_packet_results(packets,damaged)

    def test_highlight_requires_complete_epic_context(self):
        item={'key':'OPS-201','issue_type':'Story','epic_key':'OPS-200',
              'url':'https://example.atlassian.net/browse/OPS-201'}
        labels=[{'key':'OPS-201','work_type':'product_feature','execution_mode':'manual',
                 'outcome':'delivered_verified','confidence':'high','automation_candidate':False,
                 'evidence':[{'url':'https://example.atlassian.net/browse/OPS-201',
                              'fact':'Accepted release','at':'2026-10-12T10:00:00+02:00'}]}]
        assessment=[{'epic_key':'OPS-200','initiative_scope':'customer','goal':'Report export',
                     'milestone':'Release accepted','milestone_state':'delivered_verified',
                     'materiality':'high','risk_level':'none','source_checked':True,
                     'evidence':labels[0]['evidence'], 'context_sha256':sp.fingerprint(self.context_map['OPS-200'])}]
        ctx=self.context_map['OPS-200']
        complete=qg.evaluate_epics(self.snapshot,[item],labels,assessment,contexts={'OPS-200':ctx})
        self.assertEqual(complete['selected_epic_keys'],['OPS-200'])
        missing=qg.evaluate_epics(self.snapshot,[item],labels,assessment,contexts={})
        self.assertFalse(missing['pass'])
        self.assertEqual(missing['selected_epic_keys'],[])
        partial=qg.evaluate_epics(self.snapshot,[item],labels,assessment,
                                  contexts={'OPS-200':dict(ctx,context_status='partial')})
        self.assertFalse(partial['pass'])
        self.assertEqual(partial['selected_epic_keys'],[])

    def test_reporting_ownership_excludes_dwh_and_requires_verified_routing(self):
        snap=json.loads(json.dumps(self.snapshot))
        outside=dict(self.issues[4], key='DWH-900', delivery_team='DWH', reporting_scope='out_of_scope')
        result=sp.scope_ownership(snap,self.issues+[outside])
        self.assertFalse(result['pass'])
        self.assertTrue(any('cannot count as Reporting' in msg for msg in result['problems']))
        snap['reporting_ownership']['verified']=False
        self.assertFalse(sp.scope_ownership(snap,self.issues)['pass'])
        snap['reporting_ownership']['verified']=True
        snap['reporting_ownership']['excluded_other_team_issues']=[{
            'key':'DWH-900','team':'DWH','source_ref':'https://example.atlassian.net/browse/DWH-900',
            'reason':'Jira Team field inspected','ownership_verified':True}]
        snap['reporting_ownership']['provider_issue_keys'].append('DWH-900')
        snap['reporting_ownership']['provider_member_count']=11
        self.assertTrue(sp.scope_ownership(snap,self.issues)['pass'])

    def test_quality_gate_assess_blocks_unverified_scope_and_epic_context(self):
        labels=sp.read_jsonl(str(HERE/'sample_classifications.jsonl'))
        plan=qg.make_plan(self.snapshot,self.issues,labels)
        bykey={x['key']:x for x in labels}
        reviews=[{'key':key,'verdict':'agree','source_checked':True,
                  'reviewed_labels':{field:bykey[key][field] for field in ('work_type','execution_mode','outcome')},
                  'source_sha256':plan['source_sha256'],
                  'evidence_checked':[{'url':'https://example.atlassian.net/browse/'+key,'fact':'Synthetic fixture source check'}],
                  'review_note':'Synthetic source record matched'} for key in plan['review_issue_keys']]
        assessments=[{'epic_key':'OPS-200','initiative_scope':'customer','goal':'Self-service reporting',
                      'milestone':'Accepted in sprint','milestone_state':'delivered_verified','materiality':'high',
                      'risk_level':'none','source_checked':True,'evidence':bykey['OPS-201']['evidence'],
                      'context_sha256':sp.fingerprint(self.context_map['OPS-200']),
                      'source_sha256':plan['source_sha256']}]
        # Whole synthetic pipeline passes structural gates, not real source truth.
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp)
            sp.write_json(d/'snapshot.json',self.snapshot)
            sp.write_json(d/'plan.json',plan)
            sp.write_jsonl(d/'issues.jsonl',self.issues)
            sp.write_jsonl(d/'classifications.jsonl',labels)
            sp.write_jsonl(d/'reviews.jsonl',reviews)
            sp.write_jsonl(d/'assessments.jsonl',assessments)
            sp.write_jsonl(d/'epics.jsonl',self.contexts)
            source_sha=sp.fingerprint({'snapshot':self.snapshot,'issues':self.issues,'epics':self.contexts})
            source_manifest={'run_id':self.snapshot['run_id'],
                             'sprint_id':self.snapshot['sprint']['id'],
                             'source_sha256':source_sha}
            packets=sp.packetize(self.features,12,12000,self.context_map,source_sha,self.snapshot['run_id'])
            result_by_key={row['key']:row for row in labels}
            workers=[{'packet_id':packet['packet_id'],'epic_key':packet['epic_key'],
                      'run_id':packet['run_id'],'packet_sha256':packet['packet_sha256'],
                      'source_manifest_sha256':packet['source_manifest_sha256'],
                      'classifications':[result_by_key[k] for k in packet['source_issue_keys']]}
                      for packet in packets]
            sp.write_json(d/'source_manifest.json',source_manifest)
            sp.write_jsonl(d/'packets.jsonl',packets)
            sp.write_jsonl(d/'workers.jsonl',workers)
            cmd=[sys.executable,str(SCRIPTS/'quality_gate.py'),'assess',
                 '--snapshot',str(d/'snapshot.json'),'--issues',str(d/'issues.jsonl'),
                 '--epics',str(d/'epics.jsonl'),'--classifications',str(d/'classifications.jsonl'),
                 '--source-manifest',str(d/'source_manifest.json'),
                 '--packets',str(d/'packets.jsonl'),'--packet-results',str(d/'workers.jsonl'),
                 '--plan',str(d/'plan.json'),'--reviews',str(d/'reviews.jsonl'),
                 '--epic-assessments',str(d/'assessments.jsonl'),'--out',str(d)]
            result=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(sp.read_json(str(d/'highlight_selection.json'))['selected_epic_keys'],['OPS-200'])
            invalid=json.loads(json.dumps(self.snapshot))
            invalid['reporting_ownership']['verified']=False
            sp.write_json(d/'snapshot.json',invalid)
            fail=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(fail.returncode,2,fail.stderr)
            self.assertIn('source_manifest',fail.stderr.lower())
            sp.write_json(d/'snapshot.json',self.snapshot)
            incomplete=[dict(x,context_status='partial') if x['epic_key']=='OPS-200' else x
                        for x in self.contexts]
            sp.write_jsonl(d/'epics.jsonl',incomplete)
            fail=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(fail.returncode,2,fail.stderr)
            self.assertIn('source_manifest',fail.stderr.lower())

    def test_prepare_cli_requires_epics_and_reports_coverage(self):
        with tempfile.TemporaryDirectory() as d:
            base=[sys.executable,str(SCRIPTS/'sprint_pipeline.py'),'prepare',
                  '--snapshot',str(HERE/'sample_snapshot.json'),
                  '--issues',str(HERE/'sample_issues.jsonl'),'--out',d]
            missing=subprocess.run(base,capture_output=True,text=True)
            self.assertNotEqual(missing.returncode,0)
            done=subprocess.run(base+['--epics',str(HERE/'sample_epic_context.jsonl')],
                                capture_output=True,text=True)
            self.assertEqual(done.returncode,0,done.stderr)
            cov=json.loads((Path(d)/'coverage.json').read_text())
            self.assertEqual(len(cov['epic_context']['complete']),3)

if __name__=='__main__':unittest.main()
