"""Executable synthetic contract from frozen source to approved compact payload.

This test does not execute Atlassian MCP, AI workers, sharpwriter, or DuckDB.
AI outputs and the sharpwriter receipt are deliberately simulated and are NEVER
reusable as production approval artifacts.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
SCRIPTS = SKILL / 'scripts'
sys.path[:0] = [str(SCRIPTS), str(SCRIPTS / 'pages')]
import sprint_pipeline as sp
import quality_gate as qg
from validate_report import validate


class SyntheticPipelineContract(unittest.TestCase):
    def command(self, script, *args):
        result = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return result

    def make_run(self, directory: Path):
        out = directory / 'out'
        snapshot = sp.read_json(str(HERE / 'sample_snapshot.json'))
        issues = sp.read_jsonl(str(HERE / 'sample_issues.jsonl'))
        epics = sp.read_jsonl(str(HERE / 'sample_epic_context.jsonl'))
        labels = sp.read_jsonl(str(HERE / 'sample_classifications.jsonl'))
        for name, value in [('snapshot.json', snapshot)]:
            sp.write_json(directory / name, value)
        for name, value in [('issues.jsonl', issues), ('epics.jsonl', epics)]:
            sp.write_jsonl(directory / name, value)
        self.command('sprint_pipeline.py', 'prepare', '--snapshot', directory/'snapshot.json',
                     '--issues', directory/'issues.jsonl', '--epics', directory/'epics.jsonl', '--out', out)
        self.assertTrue(sp.read_json(str(out/'coverage.json'))['coverage_complete'])
        packets = sp.read_jsonl(str(out/'work_packets.jsonl'))
        lookup = {row['key']: row for row in labels}
        workers = [{'packet_id':packet['packet_id'], 'epic_key':packet['epic_key'],
                    'run_id':packet['run_id'], 'source_manifest_sha256':packet['source_manifest_sha256'],
                    'packet_sha256':packet['packet_sha256'],
                    'classifications':[lookup[key] for key in packet['source_issue_keys']]}
                   for packet in reversed(packets)]
        sp.write_jsonl(directory/'worker-results.jsonl', workers)
        self.command('sprint_pipeline.py', 'merge-packets',
                     '--packets',out/'work_packets.jsonl',
                     '--results',directory/'worker-results.jsonl','--out',out)
        merged = sp.read_jsonl(str(out/'classifications.jsonl'))
        self.assertEqual(sorted(row['key'] for row in merged), sorted(row['key'] for row in issues))
        self.command('sprint_pipeline.py','aggregate','--snapshot',directory/'snapshot.json',
                     '--issues',directory/'issues.jsonl','--classifications',out/'classifications.jsonl','--out',out)
        self.assertTrue(sp.read_json(str(out/'rollup.json'))['coverage']['coverage_complete'])
        self.command('quality_gate.py','review-plan','--snapshot',directory/'snapshot.json',
                     '--issues',directory/'issues.jsonl','--classifications',out/'classifications.jsonl','--out',out)
        plan = sp.read_json(str(out/'classification_review_plan.json'))
        reviews = [{'key':key,'verdict':'agree','source_checked':True,
                    'reviewed_labels':{field:lookup[key][field] for field in
                                       ('work_type','execution_mode','outcome')},
                    'source_sha256':plan['source_sha256'],
                    'evidence_checked':[{'url':f'https://example.atlassian.net/browse/{key}',
                                         'fact':'Synthetic reviewer checked fixture source'}],
                    'review_note':'Synthetic source record matched'}
                   for key in plan['review_issue_keys']]
        sp.write_jsonl(directory/'reviews.jsonl', reviews)
        epic_context=next(e for e in epics if e['epic_key']=='OPS-200')
        assessments=[{'epic_key':'OPS-200','initiative_scope':'customer',
                      'goal':'Customers can download reports without support',
                      'milestone':'Synthetic accepted release',
                      'milestone_state':'delivered_verified', 'materiality':'high',
                      'risk_level':'none','source_checked':True,
                      'evidence':lookup['OPS-201']['evidence'],
                      'context_sha256':sp.fingerprint(epic_context),
                      'source_sha256':plan['source_sha256']}]
        sp.write_jsonl(directory/'epic-assessments.jsonl',assessments)
        args=['--snapshot',directory/'snapshot.json', '--issues',directory/'issues.jsonl',
              '--epics',directory/'epics.jsonl','--classifications',out/'classifications.jsonl',
              '--source-manifest',out/'source_manifest.json', '--packets',out/'work_packets.jsonl',
              '--packet-results',directory/'worker-results.jsonl', '--plan',out/'classification_review_plan.json',
              '--reviews',directory/'reviews.jsonl', '--epic-assessments',directory/'epic-assessments.jsonl',
              '--out',out]
        self.command('quality_gate.py','assess',*args)
        quality=sp.read_json(str(out/'quality.json'))
        selection=sp.read_json(str(out/'highlight_selection.json'))
        self.assertTrue(quality['pass'])
        self.assertEqual(selection['selected_epic_keys'],['OPS-200'])
        return directory, out, quality, selection

    @staticmethod
    def payload():
        return {'sprint':{'schema_version':2,'id':'26.21','started_on':'2026-10-05',
                          'ended_on':'2026-10-16','period_label':'5–16 Oct 2026',
                          'executive_summary':'Synthetic customer release completed.',
                          'pulse':'Synthetic delivery.', 'attention':'', 'reviewed_issues':10,
                          'published_at':'2026-10-16T18:00:00Z','is_demo':True},
                'metrics':{'material_outcomes':1,'blocked_initiatives':0,'at_risk_initiatives':0,
                           'verified_time_saved_hours':None,'manual_operations':2,
                           'automation_candidates':1,'automation_delivered':0,'active_initiatives':1,
                           'customer_impact_score':None},
                'epics':[{'jira_key':'OPS-200','title':'Self-service reporting','domain':'Analytics',
                          'category':'product','status':'DELIVERED','objective':'Enable self-service',
                          'delivered':'Synthetic verified milestone','planned_next':'Monitor acceptance',
                          'jira_url':'https://example.atlassian.net/browse/OPS-200','highlight_rank':1,
                          'tasks':[{'jira_key':'OPS-201','title':'Customer report export',
                                    'status':'DELIVERED','outcome':'Synthetic acceptance confirmed',
                                    'jira_url':'https://example.atlassian.net/browse/OPS-201'}]}],
                'dependencies':[],
                'quality':{k:'passed' for k in ('classification','scope','evidence','sharpwriter','publication')}}

    def test_full_chain_and_hash_invalidation(self):
        with tempfile.TemporaryDirectory() as d:
            directory,out,quality,selection=self.make_run(Path(d))
            payload=self.payload()
            validate(payload)
            sp.write_json(directory/'approved-sprint.json',payload)
            report=directory/'report.md'
            report.write_text('# Synthetic executive sprint review\n\n<!-- HIGHLIGHT_EPIC:OPS-200 -->\nSynthetic acceptance.\n',encoding='utf-8')
            manifest={'report_sha256':qg.digest(report),
                      'highlighted_epic_keys':selection['selected_epic_keys']}
            sp.write_json(directory/'report-manifest.json',manifest)
            # Only a TEST FIXTURE simulates sharpwriter; production must not fabricate a receipt.
            receipt={'skill_name':'sharpwriter','status':'pass','report_sha256':qg.digest(report),
                     'approved_payload_sha256':sp.fingerprint(payload),
                     'quality_sha256':sp.fingerprint(quality),
                     'selection_sha256':sp.fingerprint(selection),
                     'source_sha256':quality['source_sha256'],
                     'review_reference':'SYNTHETIC-TEST-ONLY',
                     'checked_at':'2026-10-16T18:00:00Z','critical_issues':0,'major_issues':0,
                     'checks':{x:True for x in qg.CHECKS}}
            sp.write_json(directory/'synthetic-receipt.json',receipt)
            cmd=['publish','--quality',out/'quality.json','--selection',out/'highlight_selection.json',
                 '--report',report,'--manifest',directory/'report-manifest.json',
                 '--sharpwriter-receipt',directory/'synthetic-receipt.json',
                 '--payload',directory/'approved-sprint.json','--out',out]
            self.command('quality_gate.py',*cmd)
            self.assertTrue(sp.read_json(str(out/'publication_gate.json'))['pass'])
            tampered=copy.deepcopy(payload)
            tampered['sprint']['pulse']='The payload changed after the receipt.'
            sp.write_json(directory/'approved-sprint.json',tampered)
            result=subprocess.run([sys.executable,str(SCRIPTS/'quality_gate.py'),*map(str,cmd)],
                                  capture_output=True,text=True)
            self.assertEqual(result.returncode,4,result.stderr)
            self.assertIn('approved_payload_sha256',result.stderr)
            self.assertFalse(sp.read_json(str(out/'publication_gate.json'))['pass'])

    def test_incomplete_comment_history_blocks_assessment(self):
        with tempfile.TemporaryDirectory() as d:
            directory,out,quality,selection=self.make_run(Path(d))
            issues=sp.read_jsonl(str(directory/'issues.jsonl'))
            issues[0]['comments_complete']=False
            sp.write_jsonl(directory/'issues.jsonl',issues)
            # Frozen source manifests prevent stale worker outputs from being replayed.
            args=['assess','--snapshot',directory/'snapshot.json','--issues',directory/'issues.jsonl',
                  '--epics',directory/'epics.jsonl','--classifications',out/'classifications.jsonl',
                  '--source-manifest',out/'source_manifest.json','--packets',out/'work_packets.jsonl',
                  '--packet-results',directory/'worker-results.jsonl','--plan',out/'classification_review_plan.json',
                  '--reviews',directory/'reviews.jsonl','--epic-assessments',directory/'epic-assessments.jsonl',
                  '--out',out]
            result=subprocess.run([sys.executable,str(SCRIPTS/'quality_gate.py'),*map(str,args)],
                                  capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('source_manifest',result.stderr)

if __name__ == '__main__':
    unittest.main()
