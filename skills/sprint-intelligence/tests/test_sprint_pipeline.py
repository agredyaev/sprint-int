import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / 'scripts' / 'sprint_pipeline.py'
spec = importlib.util.spec_from_file_location('sprint_pipeline', SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class SprintPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = json.loads((HERE/'sample_snapshot.json').read_text())
        cls.issues = mod.read_jsonl(str(HERE/'sample_issues.jsonl'))
        cls.labels = mod.read_jsonl(str(HERE/'sample_classifications.jsonl'))

    def test_scope_no_parent_subtask_double_count(self):
        result = mod.summarize(self.snapshot,self.issues,self.labels)
        m = result['metrics']
        self.assertEqual(m['issues_retrieved_including_epics_subtasks'],10)
        self.assertEqual(m['root_work_item_count'],6)
        self.assertEqual(m['subtask_count'],1)
        self.assertEqual(m['root_verified_delivered_count'],2)
        self.assertEqual(m['root_manual_operational_support_count'],2)
        self.assertEqual(m['root_automation_candidate_count'],3)

    def test_activity_does_not_beat_launch(self):
        result = mod.summarize(self.snapshot,self.issues,self.labels)
        eps = {e['epic_key']:e for e in result['epics']}
        self.assertTrue(eps['OPS-100']['activity_without_verified_delivery'])
        self.assertFalse(eps['OPS-200']['activity_without_verified_delivery'])
        # A confirmed launch precedes high-volume activity in epic ordering.
        self.assertLess([x['epic_key'] for x in result['epics']].index('OPS-200'),
                        [x['epic_key'] for x in result['epics']].index('OPS-100'))

    def test_old_completion_not_counted(self):
        result = mod.summarize(self.snapshot,self.issues,self.labels)
        self.assertEqual(result['metrics']['completed_in_window_transition_count'],2)
        # includes OPS-201 and OPS-402; excludes earlier OPS-301 and subtask OPS-202.
        self.assertEqual(next(e for e in result['epics'] if e['epic_key']=='__NO_EPIC__')['completed_status_transitions'],0)

    def test_proposal_not_verified_ai(self):
        result = mod.summarize(self.snapshot,self.issues,self.labels)
        self.assertEqual(result['metrics']['execution_modes'].get('ai_automated',0),0)
        self.assertIsNone(result['metrics']['measured_net_minutes_per_sprint_known_subset'])

    def test_missing_page_declares_partial(self):
        snap = json.loads(json.dumps(self.snapshot))
        snap['extraction']['expected_issues'] = 11
        result = mod.coverage(snap,self.issues,self.labels)
        self.assertFalse(result['coverage_complete'])
        self.assertTrue(any('expected' in x for x in result['warnings']))

    def test_sprint_window_filters_old_transition(self):
        start,end = mod.window(self.snapshot)
        old = next(x for x in self.issues if x['key']=='OPS-301')
        self.assertEqual(mod.feature(old,mod.NO_EPIC,start,end)['status_events'],[])

    def test_bounded_packets_and_unique_membership(self):
        start,end = mod.window(self.snapshot)
        bykey = mod.indexes(self.issues)
        feats = [mod.feature(x,mod.root_epic(x,bykey),start,end) for x in self.issues]
        packets = mod.packetize(feats,max_items=2,max_chars=12000)
        allkeys = [key for p in packets for key in p['source_issue_keys']]
        self.assertEqual(sorted(allkeys),sorted(x['key'] for x in self.issues))
        self.assertTrue(all(len(p['issues']) <= 2 for p in packets))

    def test_invalid_or_unsupported_delivered_refused(self):
        labels = json.loads(json.dumps(self.labels))
        next(x for x in labels if x['key']=='OPS-201')['evidence'] = []
        with self.assertRaisesRegex(ValueError,'needs source evidence'):
            mod.summarize(self.snapshot,self.issues,labels)

    def test_measurement_requires_verified_baseline(self):
        labels = json.loads(json.dumps(self.labels))
        row = next(x for x in labels if x['key']=='OPS-401')
        row['automation_change'] = {'stage':'measured','technology':'rules_script','changed_in_sprint':True,
                                    'evidence':[{'source':'jira','ref':'OPS-401','at':'2026-10-12T10:00:00+02:00'}],
                                    'measurement':{'verified':False,'before_minutes_per_occurrence':15,
                                                   'after_minutes_per_occurrence':2,'occurrences_per_sprint':40}}
        with self.assertRaisesRegex(ValueError,'verified measurement'):
            mod.summarize(self.snapshot,self.issues,labels)

    def test_measured_auto_ledger_and_ai_adoption_separate(self):
        labels = json.loads(json.dumps(self.labels))
        row = next(x for x in labels if x['key']=='OPS-401')
        row['automation_change'] = {'stage':'measured','technology':'rules_script','changed_in_sprint':True,
                                    'evidence':[{'source':'jira','ref':'OPS-401','url':'https://example.atlassian.net/browse/OPS-401','at':'2026-10-12T10:00:00+02:00','fact':'Scheduled job went live'}],
                                    'measurement':{'verified':True,'before_minutes_per_occurrence':15,
                                                   'after_minutes_per_occurrence':2,'occurrences_per_sprint':40}}
        data = mod.summarize(self.snapshot,self.issues,labels)
        m = data['metrics']
        self.assertEqual(m['measured_net_minutes_per_sprint_known_subset'],520)
        self.assertEqual(m['implemented_automation_changes_in_sprint_count'],1)
        self.assertEqual(m['implemented_ai_changes_in_sprint_count'],0)
        self.assertEqual(m['automation_ledger_count_by_stage'],{'measured':1})

    def test_resolves_subtask_parent_epic(self):
        bykey=mod.indexes(self.issues)
        child=bykey['OPS-202']
        self.assertEqual(mod.root_epic(child,bykey),'OPS-200')

    def test_end_to_end_files(self):
        with tempfile.TemporaryDirectory() as d:
            args1 = [sys.executable,str(SCRIPT),'prepare','--snapshot',str(HERE/'sample_snapshot.json'),
                '--issues',str(HERE/'sample_issues.jsonl'),'--epics',str(HERE/'sample_epic_context.jsonl'),'--out',d]
            args2 = [sys.executable,str(SCRIPT),'aggregate','--snapshot',str(HERE/'sample_snapshot.json'),
                '--issues',str(HERE/'sample_issues.jsonl'),'--classifications',str(HERE/'sample_classifications.jsonl'),'--out',d]
            for args in (args1,args2):
                result = subprocess.run(args,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
            for fname in ('issue_features.jsonl','work_packets.jsonl','coverage.json','rollup.json','report-draft.md'):
                self.assertTrue((Path(d)/fname).is_file())

if __name__=='__main__':
    unittest.main()
