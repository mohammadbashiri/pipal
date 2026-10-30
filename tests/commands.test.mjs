import { test } from 'node:test';
import assert from 'node:assert/strict';
import { registerSummary as commandsExtension } from '../src/pipal/extensions/commands.ts';

for (const [args, expected] of [
  ['', 'Summarize our conversation so far.'],
  ['  decisions and next steps  ', 'Summarize our conversation so far. Focus on: decisions and next steps'],
]) {
  test(`summary is an ordinary conversational request (${args || 'default'})`, async () => {
    const commands = new Map(), messages = [];
    commandsExtension({
      registerCommand: (name, command) => commands.set(name, command),
      sendUserMessage: (text, options) => messages.push({ text, options }),
      on: () => assert.fail('No startup, shutdown, context injection or compaction hooks'),
      exec: () => assert.fail('No separate summarizer process'),
    });
    assert.deepEqual([...commands.keys()], ['pipal:summary']);
    await commands.get('pipal:summary').handler(args, {
      compact: () => assert.fail('Do not compact'),
      shutdown: () => assert.fail('Do not quit'),
      ui: { confirm: () => assert.fail('No scripted save question') },
    });
    assert.deepEqual(messages, [{ text: expected, options: { deliverAs: 'followUp' } }]);
    assert.doesNotMatch(messages[0].text, /save|summary\.md|must ask/i);
  });
}
