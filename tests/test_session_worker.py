import json
import os
from pathlib import Path
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from pipal import live_sessions as live
from pipal.session_worker import run_session
from tests.fake_live_pi import wrap_native


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('PIPAL_HOME', str(tmp_path / 'pipal-home'))
    return tmp_path


def fake_spec(root, body):
    executable = root / 'fake-pi'
    executable.write_text('#!/usr/bin/env python3\n' + body)
    executable.chmod(0o755)
    wrap_native(executable)
    return {'native_pi': str(executable), 'session_file': str(root / 'session.jsonl'),
            'directory': str(root), 'text': 'one bounded request', 'timeout_seconds': 5}


def test_shared_worker_uses_rpc_requests_durable_results_and_no_identity(isolated, monkeypatch):
    root = isolated
    launch = root / 'launch.json'
    monkeypatch.setenv('SESSION_TEST_NATIVE_ARGS', str(launch))
    # Inherited primary identity/delegation context must not leak into plain Pi.
    monkeypatch.setenv('PIPAL_AGENT_DIR', '/not-the-child')
    monkeypatch.setenv('PIPAL_TOPIC', 'not-the-child')
    spec = fake_spec(root, '''import json
print(json.dumps({'type':'message_end','message':{'role':'assistant','content':[{'type':'text','text':'A visible answer'}]}}), flush=True)
''')
    events = list(run_session(spec))
    start, final = events[0], events[-1]
    assert start['type'] == 'session_request_started'
    assert start['session']['kind'] == 'pi'
    assert start['session']['topic'] == ''
    assert final['type'] == 'session_result'
    assert final['request']['status'] == 'completed'
    assert final['final_text'] == 'A visible answer'
    args = json.loads(launch.read_text())
    assert args[:2] == ['--mode', 'rpc']
    assert '--extension' in args and args[args.index('--extension') + 1].endswith('session_bridge.ts')
    assert '-p' not in args, 'Initial work must use shared delivery, not a second prompt path'
    assert live.result_session(start['session']['session_id'], start['request_id'])['request']['status'] == 'completed'
    assert live.list_sessions() == []


def test_shared_worker_blocks_second_writer_and_releases_lock_on_close(isolated):
    spec = fake_spec(isolated, "print('must not run before delivery', flush=True)\n")
    first = run_session(spec)
    next(first)  # Registered, before initial delivery.
    try:
        with pytest.raises(RuntimeError, match='second writer'):
            list(run_session(spec))
    finally:
        first.close()
    assert live.list_sessions() == []
    # Lock is released: another normal startup can register, then close cleanly.
    second = run_session(spec)
    next(second); second.close()
    assert live.list_sessions() == []


@pytest.mark.parametrize('failure', ['model', 'timeout'])
def test_shared_worker_failure_is_not_a_success_or_delivery_retry(isolated, failure):
    counter = isolated / 'calls'
    body = f"from pathlib import Path\nwith Path({str(counter)!r}).open('a') as output: output.write('one\\n')\n"
    body += "raise SystemExit(7)\n" if failure == 'model' else "import time\ntime.sleep(10)\n"
    spec = fake_spec(isolated, body)
    if failure == 'timeout':
        spec['timeout_seconds'] = 0.5
    iterator = run_session(spec)
    start = next(iterator)
    with pytest.raises((RuntimeError, TimeoutError)):
        list(iterator)
    assert counter.read_text() == 'one\n'
    request = live.result_session(start['session']['session_id'], start['request_id'])['request']
    assert request['status'] in ('failed', 'interrupted')
    assert live.list_sessions() == []


@pytest.mark.skipif(shutil.which('pi') is None, reason='native Pi is not installed')
def test_real_native_headless_drains_peer_requests_without_polluting_original_result(tmp_path, monkeypatch):
    """Actual SDK + localhost fake model; no owner HOME/auth/session or provider."""
    home = tmp_path / 'home'; agent = home / '.pi/agent'; agent.mkdir(parents=True)
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('PI_CODING_AGENT_DIR', str(agent))
    monkeypatch.setenv('PIPAL_HOME', str(home / '.pipal'))
    started = threading.Event(); release = threading.Event()
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(data)
            text = data['messages'][-1]['content']
            text = text if isinstance(text, str) else json.dumps(text)
            tool_call = data['messages'][-1]['role'] != 'tool' and 'approval-work' in text
            if data['messages'][-1]['role'] == 'tool':
                assert 'DENIED' in text
                answer = 'Owner approval is required'
            elif 'original-work' in text:
                started.set()
                assert release.wait(10)
                answer = 'Original answer'
            else:
                answer = 'Separate peer answer'
            self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
            chunks = [({'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'approval_call', 'type': 'function', 'function': {'name': 'approval_fixture', 'arguments': '{}'}}]}, None), ({}, 'tool_calls')] if tool_call else [({'role': 'assistant', 'content': answer}, None), ({}, 'stop')]
            for delta, finish in chunks:
                event = {'id': 'fixture', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'local', 'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
                self.wfile.write(('data: ' + json.dumps(event) + '\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    (agent / 'settings.json').write_text(json.dumps({'defaultProvider': 'fixture', 'defaultModel': 'local', 'retry': {'enabled': False}, 'compaction': {'enabled': False}}))
    (agent / 'models.json').write_text(json.dumps({'providers': {'fixture': {
        'baseUrl': f'http://127.0.0.1:{server.server_address[1]}/v1', 'api': 'openai-completions', 'apiKey': 'local-fixture-only',
        'models': [{'id': 'local', 'name': 'local', 'reasoning': False, 'input': ['text'], 'contextWindow': 100000, 'maxTokens': 1000, 'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0}}],
    }}}))
    events, errors = [], []
    spec = {'native_pi': shutil.which('pi'), 'directory': str(home), 'session_file': str(home / 'native.jsonl'), 'text': 'original-work', 'timeout_seconds': 15}
    def consume():
        try:
            events.extend(run_session(spec))
        except Exception as exc:
            errors.append(exc)
    worker = threading.Thread(target=consume)
    worker.start()
    try:
        assert started.wait(10)
        target = next(s for s in live.list_sessions() if s['session_file'] == spec['session_file'])
        assert target['execution'] == 'headless'
        peer = live.message_session(target['session_id'], 'separate-peer-work')['request']
        assert peer['status'] == 'queued'
        with pytest.raises(live.LiveSessionError, match='busy'):
            live.quit_session(target['session_id'])
        release.set()
        worker.join(timeout=15)
        assert not worker.is_alive()
        assert not errors, errors
        final = next(e for e in events if e['type'] == 'session_result')
        assert final['final_text'] == 'Original answer'
        assert final['request']['reply'] == 'Original answer'
        assert all('Separate peer answer' not in json.dumps(e) for e in events)
        result = live.result_session(target['session_id'], peer['request_id'])['request']
        assert result['status'] == 'completed' and result['reply'] == 'Separate peer answer'
        assert len(calls) == 2
        assert live.list_sessions() == []
        extension = home / 'approval.ts'
        flag = home / 'must-not-exist'
        extension.write_text('''import {Type} from 'typebox';
import fs from 'node:fs';
export default function(pi){pi.registerTool({name:'approval_fixture',label:'Approval fixture',description:'Requires explicit owner approval',parameters:Type.Object({}),async execute(_id,_args,signal,_update,ctx){const approved=await ctx.ui.confirm('Approve?','This is not owner approval',{signal,timeout:5000});if(approved)fs.writeFileSync(''' + json.dumps(str(flag)) + ''','unexpected approval');return {content:[{type:'text',text:approved?'APPROVED':'DENIED'}]};}});}
''')
        settings = json.loads((agent / 'settings.json').read_text()); settings['extensions'] = [str(extension)]
        (agent / 'settings.json').write_text(json.dumps(settings))
        approval = list(run_session({**spec, 'session_file': str(home / 'approval.jsonl'), 'text': 'approval-work'}))
        assert any(e['type'] == 'session_ui_denied' and e['method'] == 'confirm' for e in approval)
        assert approval[-1]['final_text'] == 'Owner approval is required'
        assert not flag.exists(), 'Headless execution must never manufacture consent'
        assert len(calls) == 4
        assert live.list_sessions() == []
    finally:
        release.set(); worker.join(timeout=20)
        server.shutdown(); server.server_close()
