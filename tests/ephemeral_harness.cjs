// Execute the real extension tool with a fake native Pi, without provider calls.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const Module = require('node:module');
const {randomUUID} = require('node:crypto');
const esbuild = require(process.env.PIPAL_ESBUILD);
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pipal-ephemeral-test-'));
const ext = path.resolve(__dirname, '../src/pipal/extensions/delegation.ts');
const fakePi = path.join(dir, 'fake-pi');
fs.writeFileSync(fakePi, `#!/usr/bin/env python3
import json, sys, pathlib
args = sys.argv
session = pathlib.Path(args[args.index('--session') + 1])
count = len(session.read_text().splitlines()) - 1 if session.exists() else 0
count += 1
if not session.exists():
    session.write_text(json.dumps({'type': 'session', 'version': 3, 'id': 'test', 'cwd': str(pathlib.Path.cwd())}) + '\\n')
with session.open('a') as f: f.write(json.dumps({'type': 'message', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'revision %s' % count}]}}) + '\\n')
print(json.dumps({'type': 'message_end', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'revision %s' % count}], 'usage': {'input': 2, 'output': 2, 'cost': {'total': 0}}}}), flush=True)
`);
fs.chmodSync(fakePi, 0o755);
const runtimeFile = path.join(dir, 'runtime.json');
fs.writeFileSync(runtimeFile, JSON.stringify({primary: 'momo', topic: 'test', working_dir: dir, native_pi: fakePi, delegates: [], ephemeral_root: path.join(dir, 'ephemeral'), background_root: path.join(dir, 'jobs'), worker_python: process.env.PIPAL_PYTHON, agent_timeout_seconds: 5}));
process.env.PIPAL_DELEGATION_RUNTIME = runtimeFile;
const output = esbuild.buildSync({entryPoints: [ext], bundle: true, write: false, platform: 'node', format: 'cjs', packages: 'external'}).outputFiles[0].text;
const originalRequire = Module.prototype.require;
const Type = new Proxy({}, {get: () => (...args) => args[0]});
class Component { constructor() {} addChild() {} }
Module.prototype.require = function(name) {
  if (name === 'typebox') return {Type};
  if (name === '@earendil-works/pi-tui') return {Box: Component, Container: Component, Loader: Component, Markdown: Component, Spacer: Component, Text: Component};
  if (name === '@earendil-works/pi-coding-agent') return {CustomEditor: Component, getMarkdownTheme: () => ({}), ...Object.fromEntries(['Bash', 'Edit', 'Find', 'Grep', 'Ls', 'Read', 'Write'].map(x => [`create${x}ToolDefinition`, () => ({name: x.toLowerCase()})]))};
  return originalRequire.apply(this, arguments);
};
const mod = new Module(ext, module); mod.filename = ext; mod.paths = module.paths; mod._compile(output, ext);
Module.prototype.require = originalRequire;
const tools = new Map();
const pi = {registerTool: t => tools.set(t.name, t), registerCommand() {}, registerEntryRenderer() {}, registerMessageRenderer() {}, on() {}};
mod.exports.default(pi);
(async () => {
  const tool = tools.get('pipal_delegate_ephemeral');
  assert.ok(tool, 'tool must be available with no registered delegates');
  await assert.rejects(tool.execute('1', {message: 'check', role: 'Reviewer'}, undefined), /require role, provider, model, and instructions/);
  const first = await tool.execute('1', {role: 'Reviewer', provider: 'fake', model: 'fake-model', instructions: 'Check independently', message: 'first'}, undefined);
  const id = first.details.delegationId;
  assert.match(id, /^dg-[a-f0-9]{8}$/);
  assert.match(first.details.text, /revision 1/);
  const recordPath = path.join(dir, 'ephemeral', id, 'worker.json');
  assert.equal(JSON.parse(fs.readFileSync(recordPath)).model, 'fake-model');
  assert.ok(fs.existsSync(path.join(dir, 'ephemeral', id, 'transcript.jsonl')));
  // Recreate the extension to prove the follow-up survives a primary restart.
  tools.clear(); mod.exports.default(pi);
  const follow = await tools.get('pipal_delegate_ephemeral').execute('2', {delegation_id: id, message: 'correct the review'}, undefined);
  assert.match(follow.details.text, /revision 2/);
  assert.equal(follow.details.delegationId, id);
  await assert.rejects(tool.execute('3', {delegation_id: id, model: 'other', message: 'change model'}, undefined), /cannot change/);
  await tools.get('pipal_close_ephemeral').execute('4', {delegation_id: id});
  await assert.rejects(tools.get('pipal_delegate_ephemeral').execute('5', {delegation_id: id, message: 'again'}, undefined), /unavailable or closed/);
  assert.ok(fs.existsSync(JSON.parse(fs.readFileSync(recordPath)).session_file));
  assert.equal(JSON.parse(fs.readFileSync(path.join(dir, 'ephemeral', id, 'worker.json'))).closed_at !== undefined, true);
  const background = await tools.get('pipal_delegate_ephemeral').execute('6', {role: 'Auditor', provider: 'fake', model: 'fake-model', instructions: 'Audit', message: 'initial', mode: 'background'}, undefined);
  const bgId = background.details.job_id;
  const jobPath = path.join(dir, 'jobs', background.details.worker_job_id, 'job.json');
  let job;
  for (let n = 0; n < 100; n++) {
    job = JSON.parse(fs.readFileSync(jobPath, 'utf8'));
    if (job.status === 'completed' || job.status === 'failed') break;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  assert.equal(job.status, 'completed', JSON.stringify(job));
  const bgFollow = await tools.get('pipal_delegate_ephemeral').execute('7', {delegation_id: bgId, message: 'correct it'}, undefined);
  assert.match(bgFollow.details.text, /revision 2/);
  assert.equal(bgFollow.details.delegationId, bgId);
  const bgRecord = JSON.parse(fs.readFileSync(path.join(dir, 'ephemeral', bgId, 'worker.json')));
  assert.ok(fs.existsSync(bgRecord.session_file));
  assert.ok(fs.readFileSync(path.join(dir, 'ephemeral', bgId, 'transcript.jsonl'), 'utf8').includes('revision 2'));
  console.log('ephemeral lifecycle ok');
})().catch(e => { console.error(e); process.exitCode = 1; }).finally(() => fs.rmSync(dir, {recursive: true, force: true}));
