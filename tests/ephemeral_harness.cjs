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
model = args[args.index('--model') + 1] if '--model' in args else 'default'
if not session.exists():
    session.write_text(json.dumps({'type': 'session', 'version': 3, 'id': 'test', 'cwd': str(pathlib.Path.cwd())}) + '\\n')
with session.open('a') as f: f.write(json.dumps({'type': 'message', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'revision %s using %s' % (count, model)}]}}) + '\\n')
print(json.dumps({'type': 'message_end', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'revision %s using %s' % (count, model)}], 'usage': {'input': 2, 'output': 2, 'cost': {'total': 0}}}}), flush=True)
`);
fs.chmodSync(fakePi, 0o755);
const runtimeFile = path.join(dir, 'runtime.json');
fs.writeFileSync(runtimeFile, JSON.stringify({primary: 'momo', topic: 'test', working_dir: dir, native_pi: fakePi, delegates: [], ephemeral_root: path.join(dir, 'ephemeral'), model_override_root: path.join(dir, 'model-overrides'), background_root: path.join(dir, 'jobs'), worker_python: process.env.PIPAL_PYTHON, agent_timeout_seconds: 5}));
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

  const agentDir = path.join(dir, 'registered');
  fs.mkdirSync(agentDir);
  const basePrompt = path.join(agentDir, 'prompt.md');
  const baseTranscript = path.join(agentDir, 'transcript.jsonl');
  const baseSession = path.join(agentDir, 'session.jsonl');
  fs.writeFileSync(basePrompt, `You are the registered reviewer. Transcript: ${baseTranscript}`);
  fs.writeFileSync(baseTranscript, '');
  const config = JSON.parse(fs.readFileSync(runtimeFile, 'utf8'));
  config.delegates = [{agent: 'reviewer', role: 'Reviewer', provider: 'fake', model: 'saved-model', agent_path: agentDir, prompt_file: basePrompt, transcript_file: baseTranscript, session_file: baseSession}];
  fs.writeFileSync(runtimeFile, JSON.stringify(config));
  tools.clear(); mod.exports.default(pi);
  const persistent = tools.get('pipal_delegate');
  const changed = await persistent.execute('8', {agent: 'reviewer', model: 'temporary-model', message: 'review'}, undefined);
  const overrideId = changed.details.delegationId;
  assert.match(changed.details.text, /revision 1 using temporary-model/);
  const overrideDir = path.join(dir, 'model-overrides', overrideId);
  assert.equal(JSON.parse(fs.readFileSync(path.join(overrideDir, 'model.json'))).model, 'temporary-model');
  assert.equal(JSON.parse(fs.readFileSync(runtimeFile)).delegates[0].model, 'saved-model');
  assert.ok(fs.readFileSync(path.join(overrideDir, 'prompt.md'), 'utf8').includes(path.join(overrideDir, 'transcript.jsonl')));
  tools.clear(); mod.exports.default(pi);
  const continuation = await tools.get('pipal_delegate').execute('9', {agent: 'reviewer', delegation_id: overrideId, message: 'correct it'}, undefined);
  assert.match(continuation.details.text, /revision 2 using temporary-model/);
  await assert.rejects(tools.get('pipal_delegate').execute('10', {agent: 'reviewer', delegation_id: overrideId, model: 'new-model', message: 'switch'}, undefined), /fixed/);
  const ordinary = await tools.get('pipal_delegate').execute('11', {agent: 'reviewer', message: 'normal'}, undefined);
  assert.match(ordinary.details.text, /using saved-model/);
  const bgOverride = await tools.get('pipal_delegate').execute('12', {agent: 'reviewer', model: 'another-model', message: 'background review', mode: 'background'}, undefined);
  const bgOverrideJob = path.join(dir, 'jobs', bgOverride.details.worker_job_id, 'job.json');
  let overrideJob;
  for (let n = 0; n < 100; n++) {
    overrideJob = JSON.parse(fs.readFileSync(bgOverrideJob, 'utf8'));
    if (overrideJob.status === 'completed' || overrideJob.status === 'failed') break;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  assert.equal(overrideJob.status, 'completed', JSON.stringify(overrideJob));
  const afterBg = await tools.get('pipal_delegate').execute('13', {agent: 'reviewer', delegation_id: bgOverride.details.job_id, message: 'follow up'}, undefined);
  assert.match(afterBg.details.text, /revision 2 using another-model/);
  console.log('ephemeral and persistent override lifecycles ok');
})().catch(e => { console.error(e); process.exitCode = 1; }).finally(() => fs.rmSync(dir, {recursive: true, force: true}));
