import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
const root = resolve(import.meta.dirname, '..');
const seal = content => ({size:content.length, sha256:createHash('sha256').update(content).digest('hex')});
function fixture() {
  const dir=mkdtempSync(join(tmpdir(),'si-ci-'));
  const data=join(dir,'data');mkdirSync(join(data,'sprints'),{recursive:true});
  // Intentionally not valid Parquet: tests CI byte-sealing, NOT Parquet semantics.
  const bytes=Buffer.concat([Buffer.from('PAR1'),Buffer.alloc(400,65),Buffer.from('PAR1')]);
  writeFileSync(join(data,'history.parquet'),bytes);writeFileSync(join(data,'sprints','26.21.parquet'),bytes);
  const manifest={manifest_version:1,format:'sprint-intelligence-parquet',
    history:{path:'history.parquet',...seal(bytes)},
    sprints:[{id:'26.21',path:'sprints/26.21.parquet',schema_version:2,...seal(bytes)}]};
  writeFileSync(join(data,'manifest.json'),JSON.stringify(manifest));
  const out=join(dir,'out');
  return {dir,data,out,run:()=>spawnSync('bash',['ci/stage.sh',data,out],{cwd:root,encoding:'utf8'})};
}
test('manifest required and SHA-256 mismatch rejected',()=>{
  const f=fixture();try {
    assert.equal(f.run().status,0);
    writeFileSync(join(f.data,'sprints','26.21.parquet'),Buffer.from('PAR1'+ 'B'.repeat(400)+'PAR1'));
    assert.notEqual(f.run().status,0);
    assert.match(f.run().stderr,/checksum mismatch/);
    rmSync(join(f.data,'manifest.json'));
    assert.match(f.run().stderr,/Missing release manifest/);
  } finally {rmSync(f.dir,{recursive:true,force:true})}
});
test('unknown data payload and stale manifest file list rejected',()=>{
  const f=fixture();try {
    writeFileSync(join(f.data,'sprints','26.22.parquet'),Buffer.concat([Buffer.from('PAR1'),Buffer.alloc(400),Buffer.from('PAR1')]));
    assert.match(f.run().stderr,/Sprint file set differs|Unexpected data file/);
    rmSync(join(f.data,'sprints','26.22.parquet'));
    writeFileSync(join(f.data,'raw.json'),'{}');
    assert.match(f.run().stderr,/Unexpected data file/);
  } finally {rmSync(f.dir,{recursive:true,force:true})}
});
test('unlisted site files are rejected',()=>{
  const f=fixture();const extra=join(root,'site','internal-test-secret.txt');
  try {writeFileSync(extra,'test-only');assert.match(f.run().stderr,/Unexpected site file/)}
  finally {rmSync(extra,{force:true});rmSync(f.dir,{recursive:true,force:true})}
});

test('staging refuses to overwrite an unrelated directory or a parent path',()=>{
  const f=fixture();
  try {
    mkdirSync(f.out,{recursive:true});
    const keep=join(f.out,'important.txt');
    writeFileSync(keep,'keep this');
    const refused=f.run();
    assert.notEqual(refused.status,0);
    assert.match(refused.stderr,/unmarked directory/);
    assert.equal(readFileSync(keep,'utf8'),'keep this');
    const relative=spawnSync('bash',['ci/stage.sh',f.data,'..'],{cwd:root,encoding:'utf8'});
    assert.notEqual(relative.status,0);
    assert.match(relative.stderr,/Unsafe stage output path/);
  } finally {rmSync(f.dir,{recursive:true,force:true})}
});
