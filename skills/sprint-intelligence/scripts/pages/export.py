#!/usr/bin/env python3
"""Quick-only publisher: approved transient report -> canonical sprint Parquet + history index.

This script is intentionally NOT part of GitHub Actions. Amazon Quick's Python
execution environment must provide duckdb when emitting the approved snapshot.
"""
from __future__ import annotations
import argparse
import json
import os
import shutil
import tempfile
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sprint_pipeline as sp
from tempfile import mkstemp
from parquet_store import METRIC_KEYS, OPTIONAL_V2_METRICS, V2_FIELDS, _db, _sql_path, read_snapshots, write_sprint
from validate_report import validate
from asset_manifest import make_manifest, canonical_bytes

REPO = Path(__file__).resolve().parents[4]


def verify_approval(payload: dict, args: argparse.Namespace) -> None:
    """Fail closed if payload was not bound to a complete publication gate."""
    paths = [args.publication_gate,args.quality,args.selection,args.report,args.receipt]
    if any(x is None for x in paths):
        raise ValueError('Export requires --publication-gate --quality --selection --report --receipt')
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    import quality_gate as qg
    quality=sp.read_json(str(args.quality))
    selection=sp.read_json(str(args.selection))
    receipt=sp.read_json(str(args.receipt))
    approved=sp.read_json(str(args.publication_gate))
    manifest=sp.read_json(str(args.manifest)) if args.manifest else None
    if manifest is None:
        raise ValueError('Export requires --manifest')
    checked=qg.publication_check(quality,selection,receipt,manifest,args.report,payload)
    if not checked['pass'] or checked != approved:
        raise ValueError('publication gate is stale, invalid, or not bound to exact payload and report')


def rebuild_history(repo: Path, *, allow_demo: bool = False) -> Path:
    """Rebuild tiny derived index entirely from the canonical Parquet snapshots."""
    reports = read_snapshots(repo / 'data' / 'sprints', allow_demo=allow_demo)
    dest = repo / 'data' / 'history.parquet'
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = mkstemp(prefix='.history-', suffix='.parquet', dir=dest.parent)
    os.close(fd)
    connection = _db()
    try:
        index_fields = V2_FIELDS[:-1]  # Same versioned scalar columns; never copy report_json.
        connection.execute('CREATE TABLE history (' + ', '.join(f'{key} {kind}' for key,kind in index_fields) + ')')
        records = [(
            r['sprint']['id'], r['sprint'].get('schema_version', 1),
            r['sprint']['ended_on'], r['sprint']['period_label'],
            r['sprint']['published_at'], r['sprint'].get('is_demo', False),
            *(r['metrics'][key] for key in METRIC_KEYS),
            *(r['metrics'].get(key) for key in OPTIONAL_V2_METRICS),
        ) for r in reports]
        connection.executemany(
            'INSERT INTO history VALUES (' + ','.join('?' for _ in index_fields) + ')',
            records,
        )
        connection.execute(f"COPY (SELECT * FROM history ORDER BY ended_on DESC, sprint_id DESC) TO '{_sql_path(Path(temporary))}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        result = connection.execute('SELECT * FROM read_parquet(?) ORDER BY ended_on DESC, sprint_id DESC', [temporary])
        if tuple((d[0], str(d[1]).upper()) for d in result.description) != index_fields:
            raise ValueError('History index physical schema mismatch')
        if result.fetchall() != records:
            raise ValueError('History index rows do not match canonical sprint files')
        os.replace(temporary, dest)
    finally:
        connection.close()
        if os.path.exists(temporary): os.unlink(temporary)
    return dest


def publish_transaction(repo: Path, payload: dict | None, *, replace: bool = False,
                        allow_demo: bool = False) -> tuple[Path | None, Path]:
    """Prepare and verify a complete release off-path; commit manifest last.

    Exceptions roll back all canonical changes. On process termination between
    renames, existing manifest hashes no longer match; CI rejects staging.
    """
    data=repo/'data'
    canonical=data/'sprints'
    canonical.mkdir(parents=True,exist_ok=True)
    manifest_dest=data/'manifest.json'
    dest = canonical/f"{payload['sprint']['id']}.parquet" if payload else None
    if dest and dest.exists() and not replace:
        raise FileExistsError(f'{dest.name} exists; use --replace after full renewed approval')
    # Scratch files must be on the same filesystem for atomic file replacement.
    with tempfile.TemporaryDirectory(prefix='.publish-transaction-',dir=repo) as temp:
        temp_root=Path(temp)
        working=temp_root/'prepared'
        working_sprints=working/'data'/'sprints'
        working_sprints.mkdir(parents=True)
        for old in canonical.glob('*.parquet'):
            if old.is_symlink() or not old.is_file():
                raise ValueError(f'Invalid canonical sprint file {old}')
            shutil.copy2(old,working_sprints/old.name)
        if payload is not None:
            write_sprint(payload,working_sprints,replace=replace)
        # Validate and rebuild the new history from all files, including candidate.
        staged_history=rebuild_history(working,allow_demo=allow_demo)
        new_manifest=make_manifest(working,allow_demo=allow_demo)
        staged_manifest=working/'data'/'manifest.json'
        staged_manifest.write_bytes(canonical_bytes(new_manifest))
        updates=[]
        if dest:
            updates.append((working_sprints/dest.name,dest))
        updates += [(staged_history,data/'history.parquet'),(staged_manifest,manifest_dest)]
        # Keep all prior bytes until the new manifest has been committed.
        backups={}
        for _,target in updates:
            if target.exists():
                backup=temp_root/f'backup-{len(backups)}'
                shutil.copy2(target,backup)
                backups[target]=backup
            else:
                backups[target]=None
        changed=[]
        try:
            for source,target in updates:
                target.parent.mkdir(parents=True,exist_ok=True)
                os.replace(source,target)
                changed.append(target)
        except BaseException:
            for target in reversed(changed):
                previous=backups[target]
                if previous is None:
                    target.unlink(missing_ok=True)
                else:
                    os.replace(previous,target)
            raise
    return dest,data/'history.parquet'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=REPO)
    parser.add_argument('--input', type=Path, help='Approved transient compact JSON input (outside the repository)')
    parser.add_argument('--replace', action='store_true', help='Reviewed correction of an existing sprint')
    parser.add_argument('--allow-demo', action='store_true', help='Allow synthetic test fixtures (never for real reporting)')
    parser.add_argument('--index-only', action='store_true', help='Rebuild index and manifest from canonical Parquet')
    for name in ('publication-gate','quality','selection','report','receipt','manifest'):
        parser.add_argument('--'+name, type=Path, help='Transient verified publication artifact (required for write)')
    args = parser.parse_args()
    repo = args.repo.resolve()
    if not (repo/'site'/'index.html').is_file():
        parser.error('Not a Sprint Intelligence Pages repository')
    payload=None
    if args.index_only:
        if args.input:parser.error('--input cannot be used with --index-only')
    else:
        if not args.input:parser.error('--input is required unless --index-only is used')
        source=args.input.resolve()
        if source.is_relative_to(repo) and not (args.allow_demo and source.is_relative_to(repo/'examples')):
            parser.error('Transient approved JSON must be outside the Git repository')
        payload=json.loads(source.read_text(encoding='utf-8'))
        validate(payload)
        for approval_file in (args.publication_gate,args.quality,args.selection,args.report,args.receipt,args.manifest):
            if approval_file is not None and approval_file.resolve().is_relative_to(repo):
                parser.error('Publication approval artifacts must stay outside Git')
        verify_approval(payload,args)
        if payload['sprint'].get('is_demo') and not args.allow_demo:
            parser.error('Synthetic demo requires --allow-demo')
    written,index=publish_transaction(repo,payload,replace=args.replace,allow_demo=args.allow_demo)
    if written:print('Canonical sprint:',written)
    print('Derived history index:',index)
    print('SHA-256 release manifest:',repo/'data'/'manifest.json')
    print('GitHub Actions requires no Python, uv or native DuckDB')

if __name__ == '__main__':
    main()
