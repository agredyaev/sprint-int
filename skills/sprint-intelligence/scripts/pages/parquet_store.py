"""Quick-only canonical Parquet writer and versioned reader.

New snapshots use v2. Existing v1 files remain read-only and are not migrated.
The compact approved narrative stays in report_json pending a separately
reviewed change to fully columnar epic/task storage. No DuckDB database file.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from validate_report import validate

METRIC_KEYS = (
    'material_outcomes', 'blocked_initiatives', 'at_risk_initiatives',
    'verified_time_saved_hours', 'manual_operations', 'automation_candidates',
    'automation_delivered', 'active_initiatives',
)
# A documented v2 example of a nullable additive metric. This metric must
# remain NULL until an evidence-backed definition and measurement are approved.
OPTIONAL_V2_METRICS = ('customer_impact_score',)
V1_COLUMNS = ('sprint_id', 'ended_on', 'period_label', 'published_at', 'is_demo',
              *METRIC_KEYS, 'report_json')
V2_COLUMNS = ('sprint_id', 'schema_version', 'ended_on', 'period_label',
              'published_at', 'is_demo', *METRIC_KEYS, *OPTIONAL_V2_METRICS,
              'report_json')
SCHEMA_COLUMNS = V2_COLUMNS
V2_FIELDS = (
    ('sprint_id', 'VARCHAR'), ('schema_version', 'BIGINT'),
    ('ended_on', 'VARCHAR'), ('period_label', 'VARCHAR'),
    ('published_at', 'VARCHAR'), ('is_demo', 'BOOLEAN'),
    *((key, 'DOUBLE' if key in ('verified_time_saved_hours', *OPTIONAL_V2_METRICS)
       else 'BIGINT') for key in (*METRIC_KEYS, *OPTIONAL_V2_METRICS)),
    ('report_json', 'VARCHAR'),
)
V1_FIELDS = tuple(field for field in V2_FIELDS if field[0] in V1_COLUMNS)


def _db():
    try:
        import duckdb
    except ImportError as e:
        raise RuntimeError('DuckDB is required in the Amazon Quick export environment only') from e
    return duckdb.connect(':memory:')


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def _version(payload: dict) -> int:
    return payload['sprint'].get('schema_version', 1)


def _row(payload: dict, version: int | None = None) -> tuple:
    """Build one physical row using the exact declared version."""
    version = _version(payload) if version is None else version
    sprint = payload['sprint']
    base = (sprint['id'], sprint['ended_on'], sprint['period_label'],
            sprint['published_at'], sprint.get('is_demo', False))
    metrics = tuple(payload['metrics'][key] for key in METRIC_KEYS)
    report = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    if version == 1:
        return (*base, *metrics, report)
    if version == 2:
        return (base[0], 2, *base[1:], *metrics,
                *(payload['metrics'].get(key) for key in OPTIONAL_V2_METRICS), report)
    raise ValueError(f'Unsupported sprint schema_version: {version}')


def write_sprint(payload: dict, directory: Path, *, replace: bool = False) -> Path:
    """Write one reviewed v2 sprint, read it back, and replace atomically."""
    validate(payload)
    if _version(payload) != 2:
        raise ValueError('New exports require sprint.schema_version = 2')
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / f"{payload['sprint']['id']}.parquet"
    if dest.exists() and not replace:
        raise FileExistsError(f'{dest.name} exists; use --replace after full renewed approval')
    fd, tmp = tempfile.mkstemp(prefix='.sprint-', suffix='.parquet', dir=directory)
    os.close(fd)
    conn = _db()
    try:
        conn.execute('CREATE TABLE report (' + ', '.join(f'{key} {kind}' for key, kind in V2_FIELDS) + ')')
        conn.execute('INSERT INTO report VALUES (' + ','.join('?' for _ in V2_COLUMNS) + ')', _row(payload))
        conn.execute(f"COPY report TO '{_sql_path(Path(tmp))}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        restored = _read_file(conn, Path(tmp), expected_id=payload['sprint']['id'])
        if restored != payload:
            raise ValueError('Parquet round-trip changed sprint content')
        if dest.exists() and not replace:
            raise FileExistsError(f'{dest.name} already exists')
        os.replace(tmp, dest)
    finally:
        conn.close()
        if os.path.exists(tmp):
            os.unlink(tmp)
    return dest


def _read_file(conn, file: Path, expected_id: str | None = None) -> dict:
    if not file.is_file() or file.stat().st_size > 2_000_000:
        raise ValueError(f'Parquet sprint absent or exceeds 2 MB: {file}')
    try:
        result = conn.execute('SELECT * FROM read_parquet(?)', [str(file.resolve())])
        columns = tuple(d[0] for d in result.description)
        if columns not in (V1_COLUMNS, V2_COLUMNS):
            raise ValueError(f'Unexpected or unsupported Parquet schema: {file.name}')
        expected_types = V1_FIELDS if columns == V1_COLUMNS else V2_FIELDS
        physical_types = tuple((d[0], str(d[1]).upper()) for d in result.description)
        if physical_types != expected_types:
            raise ValueError(f'Parquet field types mismatch in {file.name}: {physical_types}')
        rows = result.fetchall()
        if len(rows) != 1:
            raise ValueError(f'Sprint Parquet must contain one row: {file.name}')
        typed = dict(zip(columns, rows[0]))
        payload = json.loads(typed['report_json'])
        validate(payload)
        version = 1 if columns == V1_COLUMNS else 2
        if _version(payload) != version or (version == 2 and typed['schema_version'] != 2):
            raise ValueError(f'{file.name}: payload and physical schema versions disagree')
        if expected_id and payload['sprint']['id'] != expected_id:
            raise ValueError('Sprint ID and filename disagree')
        expected = dict(zip(columns, _row(payload, version)))
        for field in columns:
            if typed[field] != expected[field]:
                raise ValueError(f'{file.name}: column {field} mismatches report payload')
        return payload
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f'Invalid Parquet sprint {file.name}: {e}') from e


def read_snapshots(directory: Path, allow_demo: bool = False) -> list[dict]:
    if not directory.is_dir():
        raise ValueError(f'Missing Parquet sprint directory: {directory}')
    if list(directory.glob('*.json')):
        raise ValueError('Canonical store must contain Parquet, not JSON')
    files = sorted(directory.glob('*.parquet'))
    if not files:
        raise ValueError('No validated Parquet sprint files')
    conn = _db()
    try:
        payloads = [_read_file(conn, f, f.stem) for f in files]
    finally:
        conn.close()
    if len({p['sprint']['id'] for p in payloads}) != len(payloads):
        raise ValueError('Duplicate sprint IDs')
    if any(p['sprint'].get('is_demo', False) for p in payloads):
        if not allow_demo:
            raise ValueError('Demo data cannot deploy without --allow-demo')
        if not all(p['sprint'].get('is_demo', False) for p in payloads):
            raise ValueError('Mixing demo and production sprint snapshots is forbidden')
    return sorted(payloads, key=lambda p: (p['sprint']['ended_on'], p['sprint']['id']), reverse=True)
