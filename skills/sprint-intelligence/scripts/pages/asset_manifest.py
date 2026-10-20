"""Quick-side content manifest for immutable Parquet snapshots and derived history.

This is a consistency seal, not a signature or proof of source authenticity.
"""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path
from parquet_store import read_snapshots

ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$")


def item(path: Path, relative: str) -> dict:
    if path.stat().st_size > 2_000_000:
        raise ValueError(f'Release Parquet file exceeds 2 MB: {relative}')
    data = path.read_bytes()
    return {"path": relative, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def make_manifest(root: Path, *, allow_demo: bool = False) -> dict:
    data = root / 'data'
    reports = read_snapshots(data / 'sprints', allow_demo=allow_demo)
    if not (data / 'history.parquet').is_file():
        raise ValueError('Missing history.parquet')
    # History content must have been rebuilt and validated before manifest creation.
    entries=[]
    for report in sorted(reports,key=lambda r:r['sprint']['id']):
        sid=report['sprint']['id']
        if not ID.fullmatch(sid):
            raise ValueError(f'Invalid sprint ID: {sid}')
        entry=item(data / 'sprints' / f'{sid}.parquet', f'sprints/{sid}.parquet')
        entry.update(id=sid, schema_version=report['sprint'].get('schema_version',1))
        entries.append(entry)
    latest=max(reports,key=lambda r:(r['sprint']['ended_on'],r['sprint']['id']))
    sprint=latest['sprint']
    metrics=latest['metrics']
    bootstrap={
        'sprint_id': sprint['id'],
        'period_label': sprint['period_label'],
        'published_at': sprint['published_at'],
        'is_demo': sprint.get('is_demo', False),
        'team': sprint['team'],
        'reviewed_issues': sprint['reviewed_issues'],
        'executive_summary': sprint['executive_summary'],
        'pulse': sprint['pulse'],
        'attention': sprint.get('attention') or '',
        'attention_owner': sprint.get('attention_owner') or '',
        'active_initiatives': metrics['active_initiatives'],
    }
    return {'manifest_version': 2,
            'format': 'sprint-intelligence-parquet',
            'history': item(data / 'history.parquet','history.parquet'),
            'sprints': entries,
            'bootstrap': bootstrap}


def canonical_bytes(manifest: dict) -> bytes:
    return (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)+'\n').encode('utf-8')
