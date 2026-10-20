import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createHash } from 'node:crypto';
import { createSprintReader } from '../site/assets/data-store.js';

const KEYS = [
  'material_outcomes', 'blocked_initiatives', 'at_risk_initiatives',
  'verified_time_saved_hours', 'manual_operations', 'automation_candidates',
  'automation_delivered', 'active_initiatives', 'customer_impact_score'
];
const metrics = Object.fromEntries(KEYS.map((name, index) => [name, index === 8 ? null : index + 1]));
const ids = ['26.18', '26.19', '26.20', '26.21'];

function fixture({tamper = null, failAt = null} = {}) {
  const originalFetch = globalThis.fetch;
  const bytes = Buffer.alloc(200, 42);
  const digest = createHash('sha256').update(bytes).digest('hex');
  const files = new Map();
  const rows = [];
  const records = new Map();
  const manifest = {sprints: []};
  for (const id of ids) {
    const path = `sprints/${id}.parquet`;
    files.set(path, {path, size:bytes.length, sha256:digest});
    manifest.sprints.push({path, id, schema_version:2, size:bytes.length, sha256:digest});
    rows.push({id, period:'Oct 1–14', ended_on:'2026-10-14', published_at:'2026-10-15T10:00:00Z', is_demo:true, metrics:{...metrics}});
    const payload = {sprint:{id, schema_version:2, period_label:'Oct 1–14',ended_on:'2026-10-14',published_at:'2026-10-15T10:00:00Z',is_demo:true},metrics:{...metrics},epics:[],dependencies:[]};
    records.set(id, {sprint_id:id,schema_version:2n,period_label:payload.sprint.period_label,ended_on:payload.sprint.ended_on,published_at:payload.sprint.published_at,is_demo:true,...metrics,report_json:JSON.stringify(payload)});
  }
  if (tamper) tamper(records, rows, manifest);
  let active = 0, maxActive = 0;
  const fetched = [], registered = [], dropped = [];
  const db = {
    async registerFileBuffer(name, buf) {registered.push(name); assert.equal(buf.byteLength, 200);},
    async dropFile(name) {dropped.push(name);},
    async terminate() {dropped.push('terminated');}
  };
  const conn = {
    async query(sql) {
      ++active; maxActive = Math.max(maxActive,active);
      const id = sql.match(/sprint_([^']+)\.parquet/)[1];
      await new Promise(resolve => setTimeout(resolve, 5));
      --active;
      if (id === failAt) throw new Error('DuckDB read failure');
      const record = records.get(id);
      return {numRows:1,toArray:()=>[{toJSON:()=>record}]};
    },
    async close() {dropped.push('connection closed');}
  };
  globalThis.fetch = async url => {
    fetched.push(String(url));
    return new Response(bytes, {status:200});
  };
  const reader = createSprintReader({db,conn,files,manifest,rows});
  return {reader, db, rows, records, fetched, registered, dropped,
    maxActive:()=>maxActive, cleanup(){globalThis.fetch = originalFetch;}};
}

test('browser releases registered Parquet after each read and bounds report cache', async () => {
  const f=fixture();
  try {
    for (const id of ids) assert.equal((await f.reader.getSprint(id)).sprint.sprint_id,id);
    assert.equal(f.registered.length,4);
    assert.deepEqual(f.dropped.slice(0,4),f.registered);
    await f.reader.getSprint('26.21');
    assert.equal(f.registered.length,4,'recent entry served from bounded cache');
    await f.reader.getSprint('26.18');
    assert.equal(f.registered.length,5,'oldest evicted entry fetched again');
    await f.reader.close();
    assert.deepEqual(f.dropped.slice(-2),['connection closed','terminated']);
    await assert.rejects(f.reader.getSprint('26.21'),/closed/);
  } finally {f.cleanup()}
});

test('concurrent sprint reads serialize one DuckDB connection and deduplicate same sprint', async () => {
  const f=fixture();
  try {
    const [a,b,c] = await Promise.all([
      f.reader.getSprint('26.18'),f.reader.getSprint('26.18'),f.reader.getSprint('26.19')
    ]);
    assert.equal(a,b);
    assert.equal(c.sprint.sprint_id,'26.19');
    assert.equal(f.maxActive(),1);
    assert.equal(f.registered.length,2);
  } finally {f.cleanup()}
});

test('stale Parquet metric is rejected, registered file released', async () => {
  const f=fixture({tamper:records=>records.get('26.20').material_outcomes++});
  try {
    await assert.rejects(f.reader.getSprint('26.20'),/metric disagrees/);
    assert.deepEqual(f.dropped,['sprint_26.20.parquet']);
    assert.equal((await f.reader.getSprint('26.19')).sprint.sprint_id,'26.19');
  } finally {f.cleanup()}
});

test('payload/index schema and metadata inconsistencies fail closed', async () => {
  const f=fixture({tamper:records=>records.get('26.20').period_label='Wrong dates'});
  try {await assert.rejects(f.reader.getSprint('26.20'),/metadata does not match/)}
  finally {f.cleanup()}
});

test('failed worker query releases registered file, later reads remain functional', async () => {
  const f=fixture({failAt:'26.19'});
  try {
    await assert.rejects(f.reader.getSprint('26.19'),/DuckDB read failure/);
    assert.deepEqual(f.dropped,['sprint_26.19.parquet']);
    assert.equal((await f.reader.getSprint('26.20')).sprint.sprint_id,'26.20');
  } finally {f.cleanup()}
});

test('malformed sprint ids cannot be interpolated into SQL paths', async () => {
  const f=fixture();
  try {await assert.rejects(f.reader.getSprint("26.18'); DROP TABLE history;--"),/Unknown sprint/)}
  finally {f.cleanup()}
});

test('unregistered Parquet columns fail schema version contract', async () => {
  const f=fixture({tamper:records=>{records.get('26.20').unexpected_metric=123;}});
  try {await assert.rejects(f.reader.getSprint('26.20'),/Unexpected Parquet column set/)}
  finally {f.cleanup()}
});

test('a missing required count is never interpreted as zero', async () => {
  const f=fixture({tamper:records=>{
    const row=records.get('26.20');
    row.manual_operations=null;
    const embedded=JSON.parse(row.report_json);
    embedded.metrics.manual_operations=null;
    row.report_json=JSON.stringify(embedded);
  }});
  try {await assert.rejects(f.reader.getSprint('26.20'),/Missing sprint metric/)}
  finally {f.cleanup()}
});
