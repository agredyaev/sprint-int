/* DuckDB-Wasm adapter. Canonical reports: Parquet; SQL runs in a Web Worker.
   Dashboard DOM never knows about DuckDB's internal row/Arrow types. */
const CDN = 'https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.29.0/+esm';
const METRICS = [
  'material_outcomes', 'blocked_initiatives', 'at_risk_initiatives',
  'verified_time_saved_hours', 'manual_operations', 'automation_candidates',
  'automation_delivered', 'active_initiatives'
];
const dir = new URL('../data/', import.meta.url);
const sprintIdRe = /^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$/;
const REPORT_CACHE_LIMIT = 3;
const BASE_COLUMNS = [
  'sprint_id', 'ended_on', 'period_label', 'published_at', 'is_demo',
  ...METRICS, 'report_json'
];

async function loadManifest() {
  const response = await fetch(new URL('manifest.json', dir), {cache: 'no-store'});
  if (!response.ok) throw new Error(`HTTP ${response.status}: release manifest`);
  const manifest = await response.json();
  if (manifest?.manifest_version !== 1 || manifest.format !== 'sprint-intelligence-parquet'
      || manifest.history?.path !== 'history.parquet' || !Array.isArray(manifest.sprints)
      || manifest.sprints.length < 1) {
    throw new Error('Unsupported release manifest');
  }
  const entries = new Map();
  for (const entry of [manifest.history, ...manifest.sprints]) {
    if (typeof entry?.path !== 'string' || !Number.isSafeInteger(entry.size) || entry.size < 100 || entry.size > 2_000_000
        || !/^[a-f0-9]{64}$/.test(entry.sha256) || entries.has(entry.path)) {
      throw new Error('Malformed release manifest file entry');
    }
    entries.set(entry.path, entry);
  }
  // Validate the full release index before fetching any Parquet file.
  const ids = new Set();
  for (const item of manifest.sprints) {
    if (typeof item?.id !== 'string' || !sprintIdRe.test(item.id)
        || item.path !== `sprints/${item.id}.parquet`
        || ![1, 2].includes(item.schema_version) || ids.has(item.id)) {
      throw new Error('Invalid sprint entry in release manifest');
    }
    ids.add(item.id);
  }
  if (entries.size !== manifest.sprints.length + 1) {
    throw new Error('Duplicate paths in release manifest');
  }
  return { manifest, entries };
}

async function loadParquet(db, filename, remotePath, files) {
  const expected = files.get(remotePath);
  if (!expected) throw new Error(`Unlisted release file: ${remotePath}`);
  const response = await fetch(new URL(remotePath, dir), { cache: 'no-store' });
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${remotePath}`);
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.byteLength !== expected.size) throw new Error(`Release file size mismatch: ${remotePath}`);
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
  const actual = [...digest].map(x => x.toString(16).padStart(2, '0')).join('');
  if (actual !== expected.sha256) throw new Error(`Release file checksum mismatch: ${remotePath}`);
  // Register already-fetched verified bytes; no HTTP Range requirement.
  await db.registerFileBuffer(filename, bytes);
}

function field(row, name) {
  if (row?.get) return row.get(name);
  return row?.toJSON?.()[name] ?? row?.[name];
}

function numericValue(value, name) {
  if (value == null) {
    if (name !== 'verified_time_saved_hours' && name !== 'customer_impact_score') throw new Error(`Missing sprint metric: ${name}`);
    return null;
  }
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0 || number > 1_000_000) {
    throw new Error(`Invalid sprint metric: ${name}`);
  }
  if (name !== 'verified_time_saved_hours' && name !== 'customer_impact_score'
      && !Number.isSafeInteger(number)) {
    throw new Error(`Non-integral sprint metric: ${name}`);
  }
  return number;
}

function assertSprintRow(record, payload, indexRow, meta) {
  if (!payload || !payload.sprint || !payload.metrics || !Array.isArray(payload.epics)
      || !Array.isArray(payload.dependencies)) {
    throw new Error(`Malformed approved sprint payload: ${meta.id}`);
  }
  const sprint = payload.sprint;
  const version = sprint.schema_version ?? 1;
  // A release cannot silently add physical columns without schema evolution.
  const expectedColumns = version === 2
    ? [...BASE_COLUMNS, 'schema_version', 'customer_impact_score'] : BASE_COLUMNS;
  if (Object.keys(record).length !== expectedColumns.length
      || expectedColumns.some(name => !Object.hasOwn(record, name))) {
    throw new Error(`Unexpected Parquet column set: ${meta.id}`);
  }
  if (sprint.id !== meta.id || record.sprint_id !== meta.id || version !== meta.schema_version
      || Number(record.schema_version ?? 1) !== version
      || record.period_label !== sprint.period_label || record.period_label !== indexRow.period
      || record.ended_on !== sprint.ended_on || record.ended_on !== indexRow.ended_on
      || record.published_at !== sprint.published_at || record.published_at !== indexRow.published_at
      || record.is_demo !== (sprint.is_demo ?? false) || record.is_demo !== indexRow.is_demo) {
    throw new Error(`Sprint metadata does not match Parquet/index: ${meta.id}`);
  }
  for (const metric of [...METRICS, 'customer_impact_score']) {
    if (metric === 'customer_impact_score' && version === 1) continue;
    const physical = numericValue(record[metric], metric);
    const indexed = indexRow.metrics[metric];
    const narrated = numericValue(payload.metrics[metric], metric);
    if (!Object.is(physical, indexed) || !Object.is(physical, narrated)) {
      throw new Error(`Sprint metric disagrees with Parquet/index: ${meta.id}/${metric}`);
    }
  }
}

/** Bounded reader: never retain all Parquet files in the DuckDB-Wasm worker. */
export function createSprintReader({ db, conn, files, manifest, rows }) {
  const history = new Map(rows.map(row => [row.id, row]));
  const meta = new Map(manifest.sprints.map(item => [item.id, item]));
  const cache = new Map();
  const inFlight = new Map();
  let queue = Promise.resolve();
  let closing = false;
  function remember(id, report) {
    cache.delete(id);
    cache.set(id, report);
    if (cache.size > REPORT_CACHE_LIMIT) cache.delete(cache.keys().next().value);
  }
  async function read(id) {
    const name = `sprint_${id}.parquet`;
    let registered = false;
    let normalized;
    try {
      await loadParquet(db, name, `sprints/${id}.parquet`, files);
      registered = true;
      // SELECT * is intentional: compare typed Parquet columns with the nested narrative.
      const result = await conn.query(`SELECT * FROM read_parquet('${name}')`);
      if (result.numRows !== 1) throw new Error(`Corrupt sprint snapshot: ${id}`);
      const row = result.toArray()[0];
      const record = row.toJSON?.() ?? row;
      const payload = JSON.parse(field(row, 'report_json'));
      assertSprintRow(record, payload, history.get(id), meta.get(id));
      const { id: _id, ...sprint } = payload.sprint;
      normalized = { ...payload, sprint: { sprint_id: id, ...sprint } };
    } finally {
      if (registered) await db.dropFile(name);
    }
    remember(id, normalized);
    return normalized;
  }
  async function getSprint(id) {
    if (typeof id !== 'string' || !sprintIdRe.test(id) || !meta.has(id)) {
      throw new Error(`Unknown sprint: ${id}`);
    }
    if (closing) throw new Error('Sprint store is closed');
    const cached = cache.get(id);
    if (cached) { remember(id, cached); return cached; }
    if (inFlight.has(id)) return inFlight.get(id);
    // One DuckDB connection is serialized; a failure must not poison later reads.
    const pending = queue.catch(() => {}).then(() => read(id));
    queue = pending;
    inFlight.set(id, pending);
    try { return await pending; }
    finally { inFlight.delete(id); }
  }
  async function close() {
    if (closing) return;
    closing = true;
    try { await queue.catch(() => {}); await conn.close(); }
    finally { await db.terminate(); cache.clear(); }
  }
  return { getSprint, close };
}

export async function openSprintStore() {
  const {manifest, entries} = await loadManifest();
  const duckdb = await import(CDN);
  const bundle = await duckdb.selectBundle(duckdb.getJsDelivrBundles());
  const workerURL = URL.createObjectURL(new Blob([
    `importScripts(${JSON.stringify(bundle.mainWorker)});`
  ], { type: 'text/javascript' }));
  let worker;
  let db;
  let conn;
  try {
    worker = new Worker(workerURL);
    db = new duckdb.AsyncDuckDB(new duckdb.ConsoleLogger(), worker);
    await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
    conn = await db.connect();
    await loadParquet(db, 'history.parquet', 'history.parquet', entries);
    const result = await conn.query(`
      SELECT sprint_id, schema_version, period_label, ended_on, published_at, is_demo,
             customer_impact_score, ${METRICS.join(', ')}
      FROM read_parquet('history.parquet')
      ORDER BY ended_on DESC, sprint_id DESC
    `);
    const rows = result.toArray().map(row => {
      const value = row.toJSON();
      return {
        id: value.sprint_id,
        label: `Sprint ${value.sprint_id}`,
        period: value.period_label,
        ended_on: value.ended_on,
        published_at: value.published_at,
        is_demo: value.is_demo,
        schema_version: Number(value.schema_version),
        metrics: {
          ...Object.fromEntries(METRICS.map(k => [k, numericValue(value[k], k)])),
          customer_impact_score: numericValue(value.customer_impact_score, 'customer_impact_score')
        }
      };
    });
    if (!rows.length) throw new Error('Empty sprint history');
    const ids = new Set(rows.map(row => row.id));
    const manifestIds = new Set(manifest.sprints.map(item => item.id));
    if (ids.size !== rows.length || ids.size !== manifestIds.size
        || [...ids].some(id => !manifestIds.has(id))) {
      throw new Error('History index does not match release manifest sprint IDs');
    }
    for (const item of manifest.sprints) {
      const historyRow = rows.find(row => row.id === item.id);
      if (historyRow.schema_version !== item.schema_version) {
        throw new Error(`Sprint schema version differs from release manifest: ${item.id}`);
      }
    }
    const reader = createSprintReader({db, conn, files: entries, manifest, rows});
    return { rows, getSprint: reader.getSprint, close: reader.close };
  } catch (error) {
    try { if (conn) await conn.close(); } catch {}
    try { if (db) await db.terminate(); else worker?.terminate(); } catch { worker?.terminate(); }
    throw error;
  } finally {
    URL.revokeObjectURL(workerURL);
  }
}
