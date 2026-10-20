"""High-priority regression tests for exact membership, transaction rollback and types."""
from __future__ import annotations
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BASE = Path(__file__).resolve().parent
SCRIPTS = BASE.parent / 'scripts'
REPO = BASE.parents[2]
sys.path[:0] = [str(SCRIPTS), str(SCRIPTS/'pages')]
import sprint_pipeline as sp
import export
from validate_report import validate


class SourceIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = sp.read_json(str(BASE/'sample_snapshot.json'))
        cls.issues = sp.read_jsonl(str(BASE/'sample_issues.jsonl'))

    def test_exact_provider_key_set_passes(self):
        result=sp.coverage(self.snapshot,self.issues)
        self.assertTrue(result['coverage_complete'],result['warnings'])

    def test_missing_reporting_issue_cannot_be_replaced_by_uncited_exclusion(self):
        snap=copy.deepcopy(self.snapshot)
        lost=self.issues[-1]['key']
        subset=self.issues[:-1]
        snap['reporting_ownership']['excluded_other_team_issue_keys']=[lost]
        result=sp.scope_ownership(snap,subset)
        self.assertFalse(result['pass'])
        self.assertIn('legacy',str(result['problems']))

    def test_dwh_owner_requires_source_checked_per_key_record(self):
        snap=copy.deepcopy(self.snapshot)
        lost=self.issues[-1]['key']
        snap['reporting_ownership']['excluded_other_team_issues']=[{
            'key':lost,'team':'Reporting',
            'source_ref':f'https://example.atlassian.net/browse/{lost}',
            'reason':'', 'ownership_verified':False}]
        result=sp.coverage(snap,self.issues[:-1])
        self.assertFalse(result['coverage_complete'])
        self.assertIn('non-Reporting',str(result['warnings']))

    def test_false_provider_universe_does_not_match_retained_members(self):
        snap=copy.deepcopy(self.snapshot)
        snap['reporting_ownership']['provider_issue_keys'] = snap['reporting_ownership']['provider_issue_keys'][:-1]
        snap['reporting_ownership']['provider_member_count'] -= 1
        self.assertFalse(sp.scope_ownership(snap,self.issues)['pass'])


class NumericContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload=json.loads((REPO/'examples/quick-payload.json').read_text())

    def test_all_count_metrics_reject_fraction_and_boolean(self):
        for key in ('material_outcomes','blocked_initiatives','at_risk_initiatives',
                    'manual_operations','automation_candidates','automation_delivered','active_initiatives'):
            for value in (1.5, True, False):
                doc=copy.deepcopy(self.payload)
                doc['metrics'][key]=value
                with self.subTest(metric=key, invalid=value),self.assertRaisesRegex(ValueError,'Invalid metric'):
                    validate(doc)

    def test_time_saved_null_and_fractional_hours_permitted(self):
        for val in (None, 1.75):
            doc=copy.deepcopy(self.payload)
            doc['metrics']['verified_time_saved_hours']=val
            validate(doc)


class TransactionTests(unittest.TestCase):
    def test_preparation_error_does_not_touch_canonical_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo=Path(tmp)
            def writer(payload,working,replace=False):
                target=working/'26.21.parquet'
                target.write_bytes(b'PAR1'+b'x'*300+b'PAR1')
                return target
            with patch.object(export,'write_sprint',side_effect=writer),patch.object(export,'rebuild_history',side_effect=RuntimeError('injected failure')):
                with self.assertRaisesRegex(RuntimeError,'injected failure'):
                    export.publish_transaction(repo,{'sprint':{'id':'26.21'}})
            self.assertFalse((repo/'data/sprints/26.21.parquet').exists())
            self.assertFalse((repo/'data/history.parquet').exists())
            self.assertFalse((repo/'data/manifest.json').exists())

    def test_failed_commit_rolls_back_existing_sprint_and_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo=Path(tmp)
            data=repo/'data'
            (data/'sprints').mkdir(parents=True)
            sprint=data/'sprints/26.21.parquet'
            history=data/'history.parquet'
            manifest=data/'manifest.json'
            initial={sprint:b'old-sprint',history:b'old-history',manifest:b'old-manifest'}
            for file,content in initial.items():file.write_bytes(content)
            def writer(payload, working, replace=False):
                target=working/'26.21.parquet'
                target.write_bytes(b'new-sprint')
                return target
            def rebuild(root,allow_demo=False):
                target=root/'data/history.parquet'
                target.write_bytes(b'new-history')
                return target
            actual_replace=export.os.replace
            calls=[0]
            def fail_second(source,target):
                calls[0]+=1
                if calls[0]==2:raise OSError('injected second rename failure')
                return actual_replace(source,target)
            with patch.object(export,'write_sprint',side_effect=writer), \
                 patch.object(export,'rebuild_history',side_effect=rebuild), \
                 patch.object(export,'make_manifest',return_value={'fake':True}), \
                 patch.object(export.os,'replace',side_effect=fail_second):
                with self.assertRaisesRegex(OSError,'injected second rename failure'):
                    export.publish_transaction(repo,{'sprint':{'id':'26.21'}},replace=True)
            for file,content in initial.items():self.assertEqual(file.read_bytes(),content)

    def test_standalone_normative_references_are_relative(self):
        skill=REPO/'skills/sprint-intelligence'
        readme=(skill/'SKILL.md').read_text()
        for name in ('QUALITY-INTEGRITY.md','SCHEMA-EVOLUTION.md'):
            self.assertIn('docs/'+name,readme)
            self.assertTrue((skill/'docs'/name).is_file())
            self.assertGreater((skill/'docs'/name).stat().st_size,500)
        for source in (REPO/'docs').glob('*.md'):
            mirror=skill/'docs'/source.name
            self.assertTrue(mirror.exists(),source.name)
            self.assertEqual(mirror.read_text(),source.read_text().replace('../skills/sprint-intelligence/','../'))

if __name__=='__main__':unittest.main()
