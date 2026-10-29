import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { EventEmitter } from 'node:events';
import { randomUUID } from 'node:crypto';
import rollingSummary from '../src/pipal/extensions/rolling_summary.ts';

test('app choices are explicit, session-scoped, single-use and do not read terminal input', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pipal-summary-quit-'));
  const oldAgent = process.env.PIPAL_AGENT_DIR, oldTopic = process.env.PIPAL_TOPIC;
  process.env.PIPAL_AGENT_DIR = dir; process.env.PIPAL_TOPIC = 'test';
  const sessionDir = path.join(dir, 'topics', 'test', 'sessions'); fs.mkdirSync(sessionDir, { recursive: true });
  const sessionFile = path.join(sessionDir, 'test.jsonl'); fs.writeFileSync(sessionFile, '');
  const hooks = new Map(), events = new EventEmitter(), states = [];
  let compacts = 0, summaries = 0, stdinReads = 0;
  events.on('pipal:summary-quit-state', state => states.push(state));
  const pi = { on: (event, callback) => hooks.set(event, callback), events,
    exec: async () => { summaries++; return { code: 0, stdout: '', stderr: '' }; } };
  const ctx = { mode: 'tui', hasUI: false, sessionManager: { getSessionId: () => 'native-test', getSessionFile: () => sessionFile, getEntries: () => [{ type: 'message', message: { role: 'user' } }] },
    compact: options => { compacts++; options.onComplete(); } };
  t.mock.method(fs, 'readSync', (_fd, buffer) => { stdinReads++; buffer.write('n'); return 1; });
  const prepare = (choice, sessionId = 'native-test') => { const requestId = randomUUID(); events.emit('pipal:summary-quit-request', { action: 'prepare', sessionId, requestId, choice }); return requestId; };
  try {
    rollingSummary(pi);
    await hooks.get('session_start')({ reason: 'startup' }, ctx);
    assert.equal(states.at(-1).protocol, 1);
    prepare('summarize'); await hooks.get('session_shutdown')({ reason: 'quit' }, ctx);
    assert.equal(compacts, 1); assert.equal(summaries, 1); assert.equal(stdinReads, 0);
    await hooks.get('session_start')({ reason: 'reload' }, ctx);
    prepare('skip'); await hooks.get('session_shutdown')({ reason: 'quit' }, ctx);
    assert.equal(compacts, 1); assert.equal(summaries, 1); assert.equal(stdinReads, 0);
    // An unselected ordinary TUI quit still asks its normal question.
    await hooks.get('session_start')({ reason: 'reload' }, ctx);
    prepare('summarize', 'another-session');
    await hooks.get('session_shutdown')({ reason: 'quit' }, ctx);
    assert.equal(stdinReads, 1); assert.equal(summaries, 1);
    // A canceled/rejected app request can clear its choice.
    await hooks.get('session_start')({ reason: 'reload' }, ctx);
    const requestId = prepare('summarize');
    events.emit('pipal:summary-quit-request', { action: 'clear', sessionId: 'native-test', requestId });
    await hooks.get('session_shutdown')({ reason: 'quit' }, ctx);
    assert.equal(stdinReads, 2); assert.equal(summaries, 1);
    // Reload never summarizes, and consumes any obsolete prepared choice.
    await hooks.get('session_start')({ reason: 'reload' }, ctx);
    prepare('summarize'); await hooks.get('session_shutdown')({ reason: 'reload' }, ctx);
    assert.equal(stdinReads, 2); assert.equal(summaries, 1);
    await hooks.get('session_start')({ reason: 'reload' }, ctx);
    await hooks.get('session_shutdown')({ reason: 'quit' }, ctx);
    assert.equal(stdinReads, 3); assert.equal(summaries, 1);
  } finally {
    if (oldAgent === undefined) delete process.env.PIPAL_AGENT_DIR; else process.env.PIPAL_AGENT_DIR = oldAgent;
    if (oldTopic === undefined) delete process.env.PIPAL_TOPIC; else process.env.PIPAL_TOPIC = oldTopic;
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
