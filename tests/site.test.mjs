import assert from 'node:assert/strict';
import {readFileSync, existsSync} from 'node:fs';
import {test} from 'node:test';

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');

test('HTML stays presentation-only, no embedded sprint data', () => {
  const page = read('../site/index.html');
  assert.match(page, /type="module"/);
  assert.doesNotMatch(page, /<script[^>]*id="sprint-data"/);
  assert.doesNotMatch(page, /Operations/);
});

test('DuckDB-Wasm reads typed metrics and selected sprint from Parquet', () => {
  const adapter = read('../site/assets/data-store.js');
  assert.match(adapter, /duckdb-wasm@1\.29\.0/);
  assert.match(adapter, /read_parquet\('history\.parquet'\)/);
  assert.match(adapter, /registerFileBuffer/);
  assert.match(adapter, /report_json/);
  assert.doesNotMatch(adapter, /read_json_auto/);
});

test('UI retains theme controls, portfolio, history, and no Python dependency', () => {
  const app = read('../site/assets/app.js');
  const html = read('../site/index.html');
  assert.match(app, /openSprintStore/);
  assert.match(app, /version\.txt/);
  assert.match(html, /id="appearance-menu"/);
  assert.match(html, /id="portfolio"/);
  assert.match(html, /id="sprintSelect"/);
  assert.equal(existsSync(new URL('../uv.lock',import.meta.url)), false);
  assert.equal(existsSync(new URL('../pyproject.toml',import.meta.url)), false);
});

test('Skill and Quick-only exporter are bundled', () => {
  assert.match(read('../skills/sprint-intelligence/SKILL.md'), /sharpwriter/);
  assert.match(read('../skills/sprint-intelligence/scripts/pages/export.py'), /rebuild_history/);
});

test('v2 index preserves nullable metric and version without client-side zero coercion', () => {
  const adapter = read('../site/assets/data-store.js');
  assert.match(adapter, /schema_version/);
  assert.match(adapter, /customer_impact_score/);
  assert.match(adapter, /numericValue\(value\.customer_impact_score/);
});


test('browser verifies release hashes and index membership before exposing a sprint', () => {
  const adapter = read('../site/assets/data-store.js');
  assert.match(adapter, /crypto\.subtle\.digest\('SHA-256'/);
  assert.match(adapter, /History index does not match release manifest sprint IDs/);
  assert.match(adapter, /Release file checksum mismatch/);
});


test('startup shell reserves dynamic layout until first sprint render', () => {
  const html = read('../site/index.html');
  const css = read('../site/assets/styles.css');
  const app = read('../site/assets/app.js');
  assert.match(html, /<body class="data-loading">/);
  assert.match(html, /assets\/app\.js" rel="modulepreload"/);
  assert.match(html, /assets\/data-store\.js" rel="modulepreload"/);
  assert.match(html, /display=optional/);
  assert.match(css, /body\.data-loading \.metrics\{min-height:274px\}/);
  assert.match(css, /body\.data-loading \.portfolio-shell\{min-height:499px\}/);
  assert.match(app, /document\.body\.classList\.remove\('data-loading'\)/);
});
