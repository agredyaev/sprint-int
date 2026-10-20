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


test('cold start paints sealed manifest bootstrap before DuckDB initialization', () => {
  const app = read('../site/assets/app.js');
  const adapter = read('../site/assets/data-store.js');
  const manifest = JSON.parse(read('../data/manifest.json'));
  assert.equal(manifest.manifest_version, 2);
  assert.equal(manifest.bootstrap.sprint_id, '26.21');
  assert.match(app, /await loadReleaseManifest\(\)/);
  assert.match(app, /renderBootstrap\(release\.manifest\.bootstrap\)/);
  assert.match(app, /openSprintStore\(release\)/);
  assert.ok(app.indexOf('renderBootstrap(release.manifest.bootstrap)') < app.indexOf('openSprintStore(release)'));
  assert.match(adapter, /export async function loadReleaseManifest/);
  assert.match(adapter, /release \?\? await loadReleaseManifest\(\)/);
});


test('executive KPI grid exposes six metrics without decorative status noise', () => {
  const app = read('../site/assets/app.js');
  const css = read('../site/assets/styles.css');
  assert.match(app, /\['active_initiatives','Active initiatives'/);
  assert.match(app, /\['automation_delivered','Automation delivered'/);
  assert.match(app, /metric-trend trend-\$\{trend\}/);
  assert.match(app, /\?'positive':'negative'/);
  assert.match(css, /\.metric-trend\.trend-positive/);
  assert.match(css, /\.metric-trend\.trend-negative/);
  assert.match(app, /status \$\{tone\}/);
  assert.match(css, /grid-template-columns:repeat\(3,minmax\(0,1fr\)\)/);
  assert.match(css, /\.status\.blocked/);
  assert.match(css, /\.status\.risk/);
  assert.doesNotMatch(app, /status-dot/);
  assert.match(css, /\.metric-label::before\{display:none!important\}/);
  assert.match(css, /\.epic\[data-status\]>\.epic-summary/);
  assert.match(css, /box-shadow:none!important/);
  assert.match(css, /body\.data-loading \.metrics\{min-height:244px\}/);
  assert.match(css, /font-family:var\(--font-display\)/);
  assert.match(css, /color:var\(--text-primary\)!important/);
  assert.match(css, /\.spark-area \.curve/);
  assert.match(css, /border:0!important/);
  assert.match(css, /\.group-title\{/);
});


test('surface radius hierarchy keeps floating windows softer than controls', () => {
  const css = read('../site/assets/styles.css');
  const app = read('../site/assets/app.js');
  assert.match(css, /--radius-window:16px/);
  assert.match(css, /--radius-panel:12px/);
  assert.match(css, /--radius-control:10px/);
  assert.match(css, /--radius-chip:6px/);
  assert.match(css, /\.dialog\{[\s\S]*border-radius:var\(--radius-window\)/);
  assert.match(css, /\.select-shell,[\s\S]*border-radius:var\(--radius-control\)/);
  assert.match(css, /\.portfolio-shell,[\s\S]*border-radius:var\(--radius-panel\)/);
  assert.match(css, /\.status,\.hl-status\{[\s\S]*border-radius:var\(--radius-chip\)/);
  assert.match(app, /spark-fill-\$\{id\}/);
  assert.match(app, /stop-opacity="\.10"/);
  assert.match(css, /\.spark-area \.curve/);
});


test('focus states stay subtle while remaining keyboard-visible', () => {
  const css = read('../site/assets/styles.css');
  assert.match(css, /--focus-outline:rgba\(89,101,232,\.30\)/);
  assert.match(css, /--focus-halo:rgba\(89,101,232,\.075\)/);
  assert.match(css, /\.select:focus-visible,[\s\S]*outline:0/);
  assert.match(css, /\.select-shell:focus-within\{[\s\S]*box-shadow:0 0 0 1px var\(--focus-outline\),0 0 0 3px var\(--focus-halo\)/);
  assert.match(css, /\.search-wrap:focus-within\{[\s\S]*box-shadow:inset 0 0 0 1px var\(--border-strong\),0 0 0 3px var\(--focus-halo\)/);
  assert.match(css, /\.filter\.active\{[\s\S]*box-shadow:none/);
});
