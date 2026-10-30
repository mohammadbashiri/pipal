import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { createRequire } from 'node:module';
import { buildSync } from 'esbuild';
const require = createRequire(import.meta.url);
const code = buildSync({ entryPoints: [new URL('../src/pipal/extensions/session_bridge.ts', import.meta.url).pathname], bundle: true, write: false, platform: 'node', format: 'cjs', packages: 'external' }).outputFiles[0].text;
const mod = { exports: {} };
new Function('require', 'module', 'exports', code)(name => {
  if (name === 'typebox') return { Type: new Proxy({}, { get: () => (...args) => args[0] }) };
  if (name === '@earendil-works/pi-tui') return { Text: class {} };
  return require(name);
}, mod, mod.exports);

test('global, Pipal and explicit extension loads share one capability; reload can initialize again', async () => {
  const bus = new EventEmitter(), hooks = new Map(), tools = [];
  const api = () => ({
    // Native Pi gives each extension a different facade over the same bus.
    events: { emit: (name, data) => bus.emit(name, data), on(name, handler) { bus.on(name, handler); return () => bus.off(name, handler); } },
    on(name, handler) { const handlers = hooks.get(name) || []; handlers.push(handler); hooks.set(name, handlers); },
    registerTool: tool => tools.push(tool.name), registerMessageRenderer() {},
  });
  for (let i = 0; i < 3; i++) mod.exports.default(api());
  assert.equal(tools.length, 5);
  assert.equal(hooks.get('session_start').length, 2, 'One presence server and one tool context initializer');
  for (const handler of hooks.get('session_shutdown')) await handler({ reason: 'reload' });
  mod.exports.default(api());
  assert.equal(tools.length, 10, 'Reload permits exactly one fresh capability instance');
  for (const handler of hooks.get('session_shutdown')) await handler({ reason: 'quit' });
  assert.equal(bus.listenerCount('pipal:session-capabilities:claim'), 0);
});
