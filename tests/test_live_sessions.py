import json
import os
from pathlib import Path
import socket
import subprocess
import threading
from uuid import uuid4

import pytest

from pipal import cli
from pipal import live_sessions as live
from pipal.cli import main


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv('PIPAL_HOME', str(tmp_path / 'pipal'))
    yield
    # Only this test's private socket directory, never an owner's socket/server.
    try:
        live.socket_root().rmdir()
    except OSError:
        pass


class Peer:
    def __init__(self, created_by=None):
        self.session_id = str(uuid4())
        self.runtime_id = str(uuid4())
        self.file = live.socket_root() / (self.runtime_id + '.sock')
        self.requests = []
        self.session = {'session_id': self.session_id, 'runtime_id': self.runtime_id, 'reference': '@session:' + self.session_id, 'agent': 'fixture', 'topic': 'test', 'created_by': created_by}
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(str(self.file))
        self.file.chmod(0o600)
        self.server.listen()
        self.stop = False
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        directory = live._private_dir(live.runtime_root() / 'sessions')
        self.record = directory / (self.session_id + '.json')
        self.record.write_text(json.dumps({'protocol': 1, **self.session, '_socket': str(self.file)}))
        self.record.chmod(0o600)

    def run(self):
        while not self.stop:
            try:
                peer, _ = self.server.accept()
            except OSError:
                break
            with peer:
                data = b''
                while b'\n' not in data:
                    chunk = peer.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                if not data:
                    continue
                request = json.loads(data.split(b'\n')[0])
                self.requests.append(request)
                if request['op'] == 'inspect':
                    result = {'session': self.session}
                elif request['op'] == 'quit':
                    result = {'accepted': True, 'session_id': self.session_id}
                else:
                    result = {'request': {'request_id': request.get('request_id'), 'session_id': self.session_id, 'status': 'completed', 'reply': 'Fixture answer'}}
                peer.sendall((json.dumps(result) + '\n').encode())

    def close(self):
        self.stop = True
        with socket.socket(socket.AF_UNIX) as wake:
            wake.connect(str(self.file))
        self.thread.join(timeout=2)
        self.server.close()
        self.file.unlink()
        self.record.unlink()


def test_list_inspect_message_and_sender_identity(runtime):
    source, target = Peer(), Peer()
    try:
        source.session['_private_fixture'] = 'Never public'
        assert len(live.list_sessions()) == 2
        assert '_private_fixture' not in live.inspect_session(source.session_id)
        assert all('_private_fixture' not in item for item in live.list_sessions())
        assert live.inspect_session('@session:' + target.session_id)['session_id'] == target.session_id
        assert live.inspect_session(target.session_id[:8])['session_id'] == target.session_id
        request_id = str(uuid4())
        result = live.message_session(target.session_id, '--literal 🧠 text', source.session_id, request_id=request_id)
        assert result['request']['request_id'] == request_id
        sent = next(request for request in target.requests if request['op'] == 'message')
        assert sent['text'] == '--literal 🧠 text'
        assert sent['sender']['session_id'] == source.session_id
        assert sent['runtime_id'] == target.runtime_id
        with pytest.raises(live.LiveSessionError, match='itself'):
            live.message_session(source.session_id, 'self', source.session_id)
        with pytest.raises(live.LiveSessionError):
            live.inspect_session('../outside')
    finally:
        source.close(); target.close()


def test_quit_requires_approval_for_someone_elses_conversation(runtime):
    source, target = Peer(), Peer()
    try:
        with pytest.raises(live.LiveSessionError, match='owner approval'):
            live.quit_session(target.session_id, source.session_id)
        assert not any(request['op'] == 'quit' for request in target.requests)
        assert live.quit_session(target.session_id, source.session_id, True)['accepted']
        target.session['created_by'] = source.session_id
        assert live.quit_session(target.session_id, source.session_id)['accepted']
        with pytest.raises(live.LiveSessionError, match='native /quit'):
            live.quit_session(source.session_id, source.session_id, True)
    finally:
        source.close(); target.close()


def test_offline_results_are_durable_and_not_replayed(runtime):
    session_id, request_id = str(uuid4()), str(uuid4())
    directory = live._private_dir(live._private_dir(live.runtime_root() / 'messages') / session_id)
    file = directory / (request_id + '.json')
    file.write_text(json.dumps({'session_id': session_id, 'request_id': request_id, 'status': 'completed', 'reply': 'Preserved answer'}))
    file.chmod(0o600)
    assert live.result_session(session_id, request_id)['request']['reply'] == 'Preserved answer'
    file.write_text(json.dumps({'session_id': session_id, 'request_id': request_id, 'status': 'running'}))
    assert live.result_session(session_id, request_id)['request']['status'] == 'interrupted'
    assert json.loads(file.read_text())['status'] == 'running', 'A read must not rewrite old runtime evidence'
    with pytest.raises(live.LiveSessionError):
        live.result_session(session_id, '../../outside')


def test_symlink_and_insecure_registry_records_are_rejected(runtime, tmp_path):
    directory = live._private_dir(live.runtime_root() / 'sessions')
    id = str(uuid4())
    outside = tmp_path / 'outside'
    outside.write_text('{}')
    (directory / (id + '.json')).symlink_to(outside)
    assert live.list_sessions() == []
    bad = live.runtime_root() / 'insecure'
    bad.mkdir(mode=0o755)
    with pytest.raises(live.LiveSessionError):
        live._private_dir(bad)
    assert outside.read_text() == '{}'


def test_cli_json_is_not_polluted_by_registry_migration(runtime, capsys):
    assert main(['live', 'list', '--json']) == 0
    assert json.loads(capsys.readouterr().out) == {'sessions': []}
    assert main(['live', 'inspect', '../outside', '--json']) == 2
    assert 'error' in json.loads(capsys.readouterr().out)


@pytest.mark.parametrize('initial_text', [None, 'An initial task'])
@pytest.mark.parametrize('kind', ['pipal', 'pi'])
def test_start_uses_private_tmux_native_pipal_and_preserves_explicit_overrides(runtime, tmp_path, monkeypatch, initial_text, kind):
    monkeypatch.setattr(live, 'get_agent', lambda name: {'path': str(tmp_path / 'agent')})
    monkeypatch.setattr(live.shutil, 'which', lambda name: '/fake/tmux')
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(live.subprocess, 'run', run)
    def sessions():
        launch = calls[0][calls[0].index('-s') + 1]
        return [{'session_id': str(uuid4()), 'managed_name': launch}]
    monkeypatch.setattr(live, 'list_sessions', sessions)
    def failed_initial(*args, **kwargs):
        raise live.LiveSessionError('Delivery uncertain; retain request fixture-id')
    monkeypatch.setattr(live, 'message_session', failed_initial)
    result = live.start_session('fixture' if kind == 'pipal' else None, 'test' if kind == 'pipal' else None, str(tmp_path), text=initial_text, provider='explicit', model='chosen', kind=kind)
    if initial_text:
        assert 'fixture-id' in result['initial_message_error']
    assert result['session']['managed_name'].startswith('pipal-')
    command = calls[0]
    assert command[1:3] == ['-S', str(live.socket_root() / 'tmux.sock')]
    if kind == 'pipal':
        assert 'from pipal.cli import main' in command[-1]
    else:
        assert 'session_bridge.ts' in command[-1]
        assert '_lock_session_for_exec' in command[-1]
        assert 'agent chat' not in command[-1]
        assert 'PIPAL_AGENT_DIR=' not in command[-1]
    assert '--provider explicit --model chosen' in command[-1]
    assert 'PIPAL_DISABLE_AUTOGREET=1' in command[-1]
    assert not str(command[2]).startswith(str(Path.home() / '.cache/pi-app'))


def test_resume_cannot_read_a_file_outside_selected_topic(runtime, tmp_path, monkeypatch):
    agent = tmp_path / 'agent'
    (agent / 'topics/test/sessions').mkdir(parents=True)
    outside = tmp_path / 'outside.jsonl'
    outside.write_text('{"private":"must not be read"}')
    monkeypatch.setattr(live, 'get_agent', lambda name: {'path': str(agent)})
    monkeypatch.setattr(live.shutil, 'which', lambda name: '/fake/tmux')
    monkeypatch.setattr(cli, '_session_header', lambda path: pytest.fail('Do not read outside the topic'))
    with pytest.raises(live.LiveSessionError, match='selected agent/topic'):
        live.start_session('fixture', 'test', str(tmp_path), session='../../../../outside.jsonl')
    assert outside.read_text() == '{"private":"must not be read"}'


def test_plain_pi_rejects_persona_fields_and_invalid_saved_files(runtime, tmp_path):
    with pytest.raises(live.LiveSessionError, match='do not have'):
        live.start_session('fixture', None, str(tmp_path), kind='pi')
    with pytest.raises(live.LiveSessionError, match='do not have'):
        live.start_session(None, 'topic', str(tmp_path), kind='pi')
    file = tmp_path / 'not-a-session.jsonl'
    file.write_text('{"type":"not-session"}')
    with pytest.raises(live.LiveSessionError, match='not a native Pi'):
        live.start_session(None, None, str(tmp_path), session=str(file), kind='pi')


def test_session_tools_and_bootstrap_regressions():
    scripts = [str(Path(__file__).with_name(name)) for name in ('session_tools.test.mjs', 'session_bridge.test.mjs')]
    result = subprocess.run(['node', '--test', *scripts], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_extension_transport_regressions():
    script = Path(__file__).with_name('live-sessions.test.mjs')
    result = subprocess.run(['node', '--test', str(script)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
