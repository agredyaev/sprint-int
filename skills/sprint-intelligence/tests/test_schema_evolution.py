"""Schema v1 read compatibility and v2 nullable-column regression tests."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[3]
SCRIPTS = HERE.parents[1] / 'scripts' / 'pages'
sys.path.insert(0, str(SCRIPTS))

import parquet_store as store
from validate_report import validate


class SchemaValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v2 = json.loads((REPO / 'examples/quick-payload.json').read_text())

    def payload(self, version):
        doc = copy.deepcopy(self.v2)
        if version == 1:
            doc['sprint'].pop('schema_version')
            doc['metrics'].pop('customer_impact_score', None)
        return doc

    def test_current_example_is_v2_and_legacy_is_accepted_for_read(self):
        validate(self.payload(2))
        validate(self.payload(1))
        self.assertEqual(store._row(self.payload(2))[1], 2)
        self.assertEqual(len(store._row(self.payload(1))), len(store.V1_COLUMNS))
        self.assertEqual(len(store._row(self.payload(2))), len(store.V2_COLUMNS))

    def test_new_exports_require_v2_even_if_v1_validates(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'require.*schema_version'):
                store.write_sprint(self.payload(1), Path(tmp))

    def test_optional_metric_null_is_not_converted_to_zero(self):
        doc = self.payload(2)
        self.assertNotIn('customer_impact_score', doc['metrics'])
        self.assertIsNone(store._row(doc)[-2])
        doc['metrics']['customer_impact_score'] = None
        validate(doc)
        self.assertIsNone(store._row(doc)[-2])
        doc['metrics']['customer_impact_score'] = 85.0
        validate(doc)
        self.assertEqual(store._row(doc)[-2], 85.0)

    def test_no_unregistered_metrics_or_nonfinite_values(self):
        doc = self.payload(2)
        doc['metrics']['unknown'] = 5
        with self.assertRaisesRegex(ValueError, 'Unrecognized metric'):
            validate(doc)
        doc['metrics'].pop('unknown')
        for invalid in (float('nan'), float('inf'), -1, 101, '85'):
            doc['metrics']['customer_impact_score'] = invalid
            with self.subTest(invalid=repr(invalid)), self.assertRaises(ValueError):
                validate(doc)

    def test_old_version_rejects_new_metric_and_unknown_version(self):
        doc = self.payload(1)
        doc['metrics']['customer_impact_score'] = 80
        with self.assertRaisesRegex(ValueError, 'Unrecognized metric'):
            validate(doc)
        doc['metrics'].pop('customer_impact_score')
        doc['sprint']['schema_version'] = 99
        with self.assertRaisesRegex(ValueError, 'Unsupported.*schema_version'):
            validate(doc)


try:
    import duckdb  # noqa F401
    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False


@unittest.skipUnless(HAS_DUCKDB, 'DuckDB is not installed in this execution environment; Quick integration test')
class ParquetIntegrationTests(unittest.TestCase):
    setUpClass = classmethod(SchemaValidationTests.setUpClass.__func__)
    payload = SchemaValidationTests.payload
    def test_v1_v2_mixed_snapshots_and_nullable_history(self):
        import export
        old = self.payload(1)
        old['sprint']['id'] = '26.20'
        old['sprint']['ended_on'] = '2026-10-02'
        old['sprint']['published_at'] = '2026-10-02T12:00:00Z'
        old['sprint']['started_on'] = '2026-09-21'
        latest = self.payload(2)
        latest['sprint']['id'] = '26.21'
        latest['metrics']['customer_impact_score'] = 85.0
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = root / 'data' / 'sprints'
            d.mkdir(parents=True)
            conn = store._db()
            try:
                conn.execute('CREATE TABLE legacy (' + ', '.join(f'{k} {t}' for k,t in store.V1_FIELDS) + ')')
                conn.execute('INSERT INTO legacy VALUES (' + ','.join('?' for _ in store.V1_COLUMNS) + ')',store._row(old))
                conn.execute(f"COPY legacy TO '{store._sql_path(d/'26.20.parquet')}' (FORMAT PARQUET, COMPRESSION ZSTD)")
            finally:
                conn.close()
            store.write_sprint(latest, d)
            snapshots = store.read_snapshots(d, allow_demo=True)
            self.assertEqual([p['sprint']['id'] for p in snapshots], ['26.21','26.20'])
            export.rebuild_history(root, allow_demo=True)
            conn = store._db()
            try:
                rows = conn.execute('SELECT sprint_id, schema_version, customer_impact_score FROM read_parquet(?) ORDER BY ended_on', [str(root/'data'/'history.parquet')]).fetchall()
                self.assertEqual(rows, [('26.20',1,None),('26.21',2,85.0)])
                count = conn.execute("SELECT count(*) FROM read_parquet(?, union_by_name = true)", [str(d/'*.parquet')]).fetchone()[0]
                self.assertEqual(count, 2)
            finally:
                conn.close()

    def test_v2_schema_mismatch_is_rejected(self):
        latest=self.payload(2)
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            path=store.write_sprint(latest,d)
            conn=store._db()
            try:
                self.assertEqual(store._read_file(conn,path),latest)
                # A wrong order is not a valid replacement for the approved schema.
                wrong=d/'wrong.parquet'
                conn.execute(f"COPY (SELECT * EXCLUDE (schema_version), schema_version FROM read_parquet('{store._sql_path(path)}')) TO '{store._sql_path(wrong)}' (FORMAT PARQUET)")
                with self.assertRaisesRegex(ValueError, 'schema'):
                    store._read_file(conn,wrong)
            finally:
                conn.close()


if __name__ == '__main__':
    unittest.main()
