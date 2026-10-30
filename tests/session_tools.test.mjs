// Fake Pi + CLI only: no subprocesses, owner registry, HOME, or provider access.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildSync } from 'esbuild';
import * as crypto from 'node:crypto';

const code = buildSync({ entryPoints: [new URL('../src/pipal/extensions/session_tools.ts', import.meta.url).pathname], bundle: true, write: false, platform: 'node', format: 'cjs', packages: 'external' }).outputFiles[0].text;
const Type = new Proxy({}, { get: () => (...args) => args[0] });
const module = { exports: {} };
const timers = new Set();
new Function('require', 'module', 'exports', 'setInterval', 'clearInterval', code)(name => {
  if (name === 'node:crypto') return crypto;
  if (name === 'typebox') return { Type };
  if (name === '@earendil-works/pi-tui') return { Text: class { constructor(text) { this.text = text; } } };
  throw new Error(`Unexpected import: ${name}`);
}, module, module.exports, callback => {
  const timer = { callback, unref() {} }; timers.add(timer); return timer;
}, timer => timers.delete(timer));
const extension = module.exports.default;
const source = '11111111-1111-4111-8111-111111111111';
const target = '22222222-2222-4222-8222-222222222222';
const session = { session_id: target, agent: 'reviewer', topic: 'design', name: 'Review window' };
const req = (status = 'queued') => ({ request: { request_id: 'r1', session_id: target, sender_session_id: source, status, reply: status === 'completed' ? 'Reviewed.' : '' } });
const tick = () => new Promise(resolve => setImmediate(resolve));
function harness(impl = async args => args[1] === 'list' ? { sessions: [session] } : req()) {
  const hooks = new Map(), tools = new Map(), entries = [], messages = [], events = [], notices = [], calls = [], providers = [];
  let id = source;
  const pi = {
    events: { emit: (name, data) => {
      assert.equal(name, 'pipal:session-visible');
      assert.equal(data.session_id, id);
      assert.equal(data.message.role, 'custom');
      assert.equal(typeof data.message.timestamp, 'number');
      const { role, timestamp, ...message } = data.message;
      assert.deepEqual(message, messages.at(-1));
      events.push({ name, data });
    } },
    on: (name, handler) => hooks.set(name, handler), registerTool: tool => tools.set(tool.name, tool),
    registerEntryRenderer() {}, registerMessageRenderer() {}, appendEntry: (type, data) => entries.push({ type, data }),
    sendMessage: (message, options) => {
      assert.deepEqual(options, { triggerTurn: false });
      assert.equal(message.display, true);
      assert.ok(['pipal-session-outbound', 'pipal-session-display'].includes(message.customType));
      assert.ok(message.details.request_id);
      assert.ok(message.details.session_id);
      assert.ok(message.details.status);
      messages.push(message);
    }, sendUserMessage: () => assert.fail('No source model prompt'),
    exec: async (command, args, options) => {
      assert.equal(command, 'pipal'); assert.equal(args.at(-1), '--json');
      calls.push({ args, options });
      const result = await impl(args, options);
      return result?.stdout !== undefined ? result : { code: 0, stdout: JSON.stringify(result) };
    },
  };
  extension(pi);
  const ctx = { mode: 'tui', sessionManager: { getSessionId: () => id, getBranch: () => [] }, ui: {
    notify: (...args) => notices.push(args), addAutocompleteProvider: factory => providers.push(factory),
  } };
  const start = async () => { hooks.get('session_start')({}, ctx); await tick(); };
  const stop = () => hooks.get('session_shutdown')({}, ctx);
  const execute = (name, params, signal) => tools.get(`pipal_session_${name}`).execute('call', params, signal, undefined, ctx);
  const input = text => hooks.get('input')({ source: 'interactive', text }, ctx);
  return { hooks, tools, entries, messages, events, notices, calls, providers, ctx, start, stop, execute, input, setId: value => { id = value; } };
}

test('all five tools use JSON argument arrays, real source identity, explicit model and safe text', async () => {
  const h = harness();
  await h.start();
  try {
    assert.equal(h.tools.size, 5);
    const ac = new AbortController();
    await h.execute('list', {});
    await h.execute('list', { session: '@session:2222' });
    await h.execute('start', { agent: 'a', topic: 't', directory: '/tmp/a b', session: 'saved', text: '-danger\nhello', model: 'm', provider: 'p' }, ac.signal);
    await h.execute('message', { target: '2222', text: '--quit', wait: 30, request_id: source });
    await h.execute('result', { target, request_id: 'r1', wait: 0 });
    await h.execute('quit', { target });
    const start = h.calls.find(c => c.args[1] === 'start');
    assert.deepEqual(start.args, ['live', 'start', '--agent', 'a', '--topic', 't', '--directory', '/tmp/a b', '--sender-session', source, '--session', 'saved', '--model', 'm', '--provider', 'p', '--text=-danger\nhello', '--json']);
    assert.equal(start.options.signal.aborted, false);
    ac.abort();
    assert.equal(start.options.signal.aborted, true, 'Tool cancellation propagates through the lifecycle-composed signal');
    assert.deepEqual(h.calls.find(c => c.args[1] === 'message').args, ['live', 'message', '2222', '--text=--quit', '--sender-session', source, '--request-id', source, '--wait', '30', '--json']);
    assert.ok(h.calls.some(c => c.args[1] === 'inspect'));
    assert.ok(h.entries.some(e => e.type === 'pipal-session-request' && e.data.request_id === 'r1'));
    const before = h.calls.length;
    await assert.rejects(h.execute('start', { agent: 'a', topic: 't', directory: '/tmp', provider: 'p' }), /requires model/);
    assert.equal(h.calls.length, before);
  } finally { h.stop(); }
});

test('plain Pi start is explicit, persona-free, and rejects Pipal-only fields', async () => {
  const h = harness(); await h.start();
  try {
    await h.execute('start', { kind: 'pi', directory: '/tmp/plain', text: 'Hello', session: '/tmp/saved.jsonl' });
    const args = h.calls.find(c => c.args[1] === 'start').args;
    assert.deepEqual(args, ['live','start','--kind','pi','--directory','/tmp/plain','--sender-session',source,'--session','/tmp/saved.jsonl','--text=Hello','--json']);
    const before = h.calls.length;
    await assert.rejects(h.execute('start', { kind: 'pi', directory: '/tmp', agent: 'persona' }), /do not have/);
    await assert.rejects(h.execute('start', { kind: 'pi', directory: '/tmp', topic: 'topic' }), /do not have/);
    await assert.rejects(h.execute('start', { kind: 'pipal', directory: '/tmp' }), /require an agent/);
    assert.equal(h.calls.length, before);
  } finally { h.stop(); }
});

test('CLI errors and malformed JSON fail tools without retry', async () => {
  for (const result of [{ code: 1, stdout: '{"error":"busy"}' }, { code: 0, stdout: 'garbage' }]) {
    const h = harness(async () => result);
    await assert.rejects(h.execute('quit', { target }), /busy|invalid JSON/);
    assert.equal(h.calls.length, 1);
  }
});

test('direct leading session route returns synchronously while delivery is unresolved', async () => {
  let finish;
  const h = harness(async args => args[1] === 'list' ? { sessions: [session] } : new Promise(resolve => { finish = resolve; }));
  await h.start();
  try {
    assert.deepEqual(h.input(`@session:${target} -hello @agent:other`), { action: 'handled' });
    assert.ok(finish);
    assert.equal(h.calls.filter(c => c.args[1] === 'message').length, 1);
    finish(req('completed')); await tick();
    const text = h.messages.filter(e => e.customType === 'pipal-session-display').at(-1).content;
    assert.equal(h.messages[0].customType, 'pipal-session-outbound');
    assert.match(text, /reviewer \/ design \/ Review window/);
    assert.match(text, /r1 · completed\nReviewed\./);
    assert.deepEqual(h.input(`Please discuss @session:${target} hi`), { action: 'continue' });
  } finally { h.stop(); }
});

test('pending ID survives restart; passive retrieval displays once and never retransmits', async () => {
  const h = harness(async args => args[1] === 'list' ? { sessions: [session] } : req('completed'));
  h.ctx.sessionManager.getBranch = () => [{ type: 'custom', customType: 'pipal-session-request', data: { target, request_id: 'r1', source_session_id: source, status: 'queued' } }];
  await h.start();
  try {
    assert.equal(h.calls.filter(c => c.args[1] === 'result').length, 1);
    assert.equal(h.calls.filter(c => c.args[1] === 'message').length, 0);
    assert.equal(h.messages.filter(e => e.customType === 'pipal-session-display').length, 1);
    assert.equal(h.entries.find(e => e.type === 'pipal-session-request').data.source_session_id, source);
    assert.equal(h.entries.find(e => e.type === 'pipal-session-request').data.status, 'completed');
  } finally { h.stop(); }
});

test('shutdown and source session replacement suppress in-flight delivery results', async () => {
  for (const invalidate of [h => h.stop(), h => h.setId('replacement')]) {
    let finish;
    const h = harness(async args => args[1] === 'list' ? { sessions: [] } : new Promise(resolve => { finish = resolve; }));
    await h.start();
    try {
      h.input(`@session:${target} hi`);
      const signal = h.calls.at(-1).options.signal;
      const before = h.entries.length, displayed = h.messages.length;
      invalidate(h); finish(req('completed')); await tick();
      assert.equal(h.entries.length, before);
      assert.equal(h.messages.length, displayed);
      assert.equal(h.notices.length, 0);
      if (h.ctx.sessionManager.getSessionId() === source) assert.equal(signal.aborted, true);
    } finally { h.stop(); }
  }
});

test('autocomplete uses cached sessions, full IDs, friendly labels, and composes with other providers', async () => {
  const h = harness(); await h.start();
  try {
    let fallback = 0, apply = 0;
    const provider = h.providers[0]({
      getSuggestions: async () => { fallback++; return { fallback: true }; },
      applyCompletion: () => { apply++; return 'applied'; },
      shouldTriggerFileCompletion: () => false,
    });
    const count = h.calls.length, options = { signal: new AbortController().signal };
    for (let i = 0; i < 20; i++) {
      const result = await provider.getSuggestions(['@session:rev'], 0, 12, options);
      assert.equal(result.items[0].value, `@session:${target}`);
      assert.equal(result.items[0].label, 'reviewer / design / Review window');
    }
    assert.equal(h.calls.length, count);
    assert.deepEqual(await provider.getSuggestions(['@agent:rev'], 0, 10, options), { fallback: true });
    assert.equal(fallback, 1);
    assert.equal(provider.applyCompletion([], 0, 0, {}, ''), 'applied'); assert.equal(apply, 1);
    assert.equal(provider.shouldTriggerFileCompletion([], 0, 0), false);
    h.stop();
    assert.equal(await provider.getSuggestions(['@session:'], 0, 9, options), null);
  } finally { h.stop(); }
});

test('quit unmanaged flag requires explicit owner UI approval and guards session replacement during approval', async () => {
  const h = harness(); await h.start();
  try {
    const before = h.calls.length;
    await assert.rejects(h.execute('quit', { target, confirm_unmanaged: true }), /Owner approval/);
    assert.equal(h.calls.length, before);
    h.ctx.hasUI = true;
    h.ctx.ui.confirm = async () => false;
    await assert.rejects(h.execute('quit', { target, confirm_unmanaged: true }), /Owner approval/);
    h.ctx.ui.confirm = async () => true;
    await h.execute('quit', { target, confirm_unmanaged: true });
    assert.ok(h.calls.at(-1).args.includes('--confirm-unmanaged'));
    h.ctx.ui.confirm = async () => { h.setId('replacement'); return true; };
    const count = h.calls.length;
    await assert.rejects(h.execute('quit', { target, confirm_unmanaged: true }), /Source session changed/);
    assert.equal(h.calls.length, count);
  } finally { h.stop(); }
});

test('passive polling completes queued direct messages exactly once; timer cleanup is lifecycle-safe', async () => {
  const h = harness(async args => args[1] === 'list' ? { sessions: [session] } : req(args[1] === 'result' ? 'completed' : 'queued'));
  await h.start();
  try {
    h.input(`@session:${target} hello`); await tick();
    for (const t of timers) t.callback(); await tick();
    for (const t of timers) t.callback(); await tick();
    assert.equal(h.calls.filter(c => c.args[1] === 'message').length, 1);
    assert.equal(h.calls.filter(c => c.args[1] === 'result').length, 1);
    assert.equal(h.messages.filter(e => e.customType === 'pipal-session-display' && e.content.includes('Reviewed.')).length, 1);
    const call = h.calls.find(c => c.args[1] === 'message');
    assert.match(call.args[call.args.indexOf('--request-id') + 1], /^[0-9a-f-]{36}$/);
  } finally { h.stop(); }
  assert.equal(timers.size, 0);
});

test('extension and RPC leading mentions route without model turns; non-leading mentions continue', async () => {
  for (const inputSource of ['extension', 'rpc']) {
    const h = harness(async args => args[1] === 'list' ? { sessions: [session] } : req('completed'));
    if (inputSource === 'rpc') h.ctx.mode = 'rpc';
    await h.start();
    try {
      const handle = text => h.hooks.get('input')({ source: inputSource, text }, h.ctx);
      assert.deepEqual(handle(`Discuss @session:${target} please`), { action: 'continue' });
      assert.deepEqual(handle(`@session:${target} hello`), { action: 'handled' });
      await tick();
      assert.equal(h.calls.filter(c => c.args[1] === 'message').length, 1);
      assert.equal(h.messages.length, 2);
      assert.equal(h.messages[0].customType, 'pipal-session-outbound');
      assert.equal(h.messages[1].customType, 'pipal-session-display');
      assert.equal(h.events.length, 2);
      assert.equal(h.events[0].data.session_id, source);
      assert.equal(h.events[1].data.message.details.session_id, target);
      assert.equal(h.events[1].data.message.details.request_id, 'r1');
      assert.match(h.events[1].data.message.content, /Reviewed\./);
      if (inputSource === 'rpc') assert.equal(h.providers.length, 0);
    } finally { h.stop(); }
  }
});

test('RPC passive retrieval restores only same-source bookkeeping; fork and legacy entries are ignored', async () => {
  for (const storedSource of [source, 'fork-parent', undefined]) {
    const h = harness(async args => args[1] === 'list' ? { sessions: [session] } : req('completed'));
    h.ctx.mode = 'rpc';
    h.ctx.sessionManager.getBranch = () => [{ type: 'custom', customType: 'pipal-session-request', data: {
      target, request_id: 'r1', source_session_id: storedSource, status: 'queued',
    } }];
    await h.start();
    try {
      assert.equal(h.calls.filter(c => c.args[1] === 'result').length, storedSource === source ? 1 : 0);
      assert.equal(h.messages.length, storedSource === source ? 1 : 0);
      assert.equal(h.providers.length, 0);
    } finally { h.stop(); }
  }
});

test('RPC shutdown prevents stale in-flight passive result display', async () => {
  let finish;
  const h = harness(async args => args[1] === 'list' ? { sessions: [] } : new Promise(resolve => { finish = resolve; }));
  h.ctx.mode = 'rpc';
  h.ctx.sessionManager.getBranch = () => [{ type: 'custom', customType: 'pipal-session-request', data: {
    target, request_id: 'r1', source_session_id: source, status: 'queued',
  } }];
  await h.start();
  assert.ok(finish);
  const signal = h.calls.at(-1).options.signal;
  h.stop();
  finish(req('completed')); await tick();
  assert.equal(signal.aborted, true);
  assert.equal(h.messages.length, 0);
  assert.equal(h.entries.length, 0);
});

test('delivery and passive result errors are visible context and scoped events without retries', async () => {
  for (const failure of ['message', 'result']) {
    const h = harness(async args => {
      if (args[1] === 'list') return { sessions: [session] };
      if (args[1] === failure) throw new Error('Transport unavailable');
      return req('queued');
    });
    h.ctx.mode = 'rpc';
    await h.start();
    try {
      h.input(`@session:${target} hello`); await tick();
      if (failure === 'result') {
        for (const t of timers) t.callback(); await tick();
        for (const t of timers) t.callback(); await tick();
      }
      assert.equal(h.calls.filter(c => c.args[1] === 'message').length, 1);
      assert.equal(h.calls.filter(c => c.args[1] === failure).length, 1);
      const error = h.messages.at(-1);
      assert.equal(error.customType, 'pipal-session-display');
      assert.equal(error.details.status, 'failed');
      assert.equal(error.details.session_id, target);
      assert.match(error.content, /Transport unavailable/);
      assert.match(error.content, /Not retried/);
      assert.ok(error.content.includes(error.details.request_id));
      assert.equal(h.events.at(-1).data.session_id, source);
      assert.equal(h.events.length, h.messages.length);
    } finally { h.stop(); }
  }
});

test('tree navigation cancels stale branch replies without stacking autocomplete providers', async () => {
  let finish;
  const h = harness(async args => args[1] === 'list' ? { sessions: [session] } : new Promise(resolve => { finish = resolve; }));
  await h.start();
  try {
    h.input(`@session:${target} old branch`);
    await tick();
    const signal = h.calls.at(-1).options.signal;
    const providers = h.providers.length;
    h.hooks.get('session_tree')({}, h.ctx);
    assert.equal(signal.aborted, true);
    finish(req('completed')); await tick();
    assert.equal(h.messages.filter(m => m.customType === 'pipal-session-display').length, 0);
    assert.equal(h.providers.length, providers);
    assert.equal(timers.size, 1);
  } finally { h.stop(); }
});

test('empty direct message or attachments are consumed without delivery', async () => {
  const h = harness(); await h.start();
  try {
    const before = h.calls.length;
    assert.deepEqual(h.input(`@session:${target}`), { action: 'handled' });
    assert.deepEqual(h.hooks.get('input')({ source: 'interactive', text: `@session:${target} hi`, images: [{}] }, h.ctx), { action: 'handled' });
    assert.equal(h.calls.length, before);
    assert.equal(h.notices.length, 2);
  } finally { h.stop(); }
});
