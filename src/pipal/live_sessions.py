"""Local live-session discovery and RPC. Pi remains the sole conversation writer."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import time
from uuid import UUID, uuid4

from .registry import get_agent, pipal_dir
from .topic_storage import topic_sessions_dir, validate_topic_name


class LiveSessionError(ValueError):
    pass


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise LiveSessionError(f"Runtime directory must be owner-only and not a symlink: {path}")
    return path


def runtime_root() -> Path:
    return _private_dir(pipal_dir().resolve() / "runtime")


def socket_root() -> Path:
    # macOS Unix sockets have a very short path limit. Do not use a long TMPDIR.
    digest = hashlib.sha256(str(pipal_dir().resolve()).encode()).hexdigest()[:12]
    return _private_dir(Path('/tmp') / f"pipal-live-{os.getuid()}-{digest}")


def _canonical_id(value: str) -> str:
    try:
        canonical = str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise LiveSessionError("Invalid session or request ID") from None
    if value != canonical:
        raise LiveSessionError("Use the canonical session or request UUID")
    return canonical


def _read_record(path: Path) -> dict:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 1024 * 1024:
        raise LiveSessionError("Unsafe runtime record")
    with path.open() as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise LiveSessionError("Invalid runtime record")
    return value


def _public(record: dict) -> dict:
    return {key: value for key, value in record.items() if not key.startswith('_')}


def _rpc(record: dict, op: str, **payload) -> dict:
    endpoint = Path(record.get('_socket', ''))
    if endpoint.parent != socket_root() or not re.fullmatch(r"[a-f0-9-]{36}\.sock", endpoint.name):
        raise LiveSessionError("Invalid session endpoint")
    info = endpoint.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise LiveSessionError("Unsafe session endpoint")
    request = {'protocol': 1, 'session_id': record['session_id'], 'runtime_id': record['runtime_id'], 'op': op, **payload}
    wait = payload.get('wait', 0)
    try:
        with socket.socket(socket.AF_UNIX) as peer:
            peer.settimeout(max(3.0, float(wait) + 3))
            peer.connect(str(endpoint))
            peer.sendall((json.dumps(request) + '\n').encode())
            data = bytearray()
            while b'\n' not in data:
                chunk = peer.recv(65536)
                if not chunk:
                    raise LiveSessionError("Session disconnected; delivery may be uncertain. Check the request ID, do not resend automatically.")
                data.extend(chunk)
                if len(data) > 1024 * 1024:
                    raise LiveSessionError("Session response exceeded its limit")
        response = json.loads(data.split(b'\n', 1)[0])
    except (OSError, json.JSONDecodeError) as exc:
        raise LiveSessionError(f"Live session unavailable; do not automatically resend: {exc}") from None
    if response.get('error'):
        raise LiveSessionError(response['error'])
    return response


def _records() -> list[dict]:
    directory = _private_dir(runtime_root() / 'sessions')
    records = []
    for path in directory.glob('*.json'):
        try:
            record = _read_record(path)
            if record.get('protocol') != 1 or path.stem != _canonical_id(record.get('session_id')):
                continue
            _canonical_id(record.get('runtime_id'))
            records.append(record)
        except (OSError, ValueError, TypeError):
            continue
    return records


def list_sessions(*, pid: int | None = None, session_file: Path | None = None) -> list[dict]:
    sessions = []
    for record in _records():
        try:
            # Owned-child startup must not probe unrelated (possibly stalled) runtimes.
            if pid is not None and record.get('pid') != pid:
                continue
            if session_file is not None and (not record.get('session_file') or Path(record['session_file']).resolve() != session_file.resolve()):
                continue
            current = _rpc(record, 'inspect')['session']
            sessions.append(_public(current))
        except (OSError, ValueError, KeyError, TypeError):
            # A PID by itself is not proof of liveness or ownership.
            continue
    return sorted(sessions, key=lambda item: (item.get('agent', ''), item.get('topic', ''), item['session_id']))


def _resolve(target: str) -> dict:
    target = target.removeprefix('@session:')
    if not re.fullmatch(r'[a-f0-9-]{8,36}', target):
        raise LiveSessionError('Use @session:<native UUID> or an unambiguous ID prefix of at least 8 characters')
    candidates = [record for record in _records() if record['session_id'].startswith(target)]
    live = []
    for record in candidates:
        try:
            _rpc(record, 'inspect')
            live.append(record)
        except (OSError, ValueError):
            continue
    if len(live) != 1:
        raise LiveSessionError('Session not running' if not live else 'Ambiguous session reference; use its full native UUID')
    return live[0]


def inspect_session(target: str) -> dict:
    return _public(_rpc(_resolve(target), 'inspect')['session'])


def _sender(sender_session: str | None, sender_name: str | None = None) -> dict:
    if sender_session:
        record = inspect_session(_canonical_id(sender_session))
        return {key: record.get(key) for key in ('session_id', 'kind', 'agent', 'topic', 'name', 'directory')}
    if sender_name is not None and (not isinstance(sender_name, str) or not sender_name.strip() or len(sender_name) > 200):
        raise LiveSessionError('Sender label must contain 1–200 characters')
    return {'session_id': None, 'name': sender_name or 'Owner (local CLI)'}


def message_session(target: str, text: str, sender_session: str | None = None, wait: float = 0, request_id: str | None = None, *, sender_name: str | None = None, sender_snapshot: dict | None = None, expected_runtime_id: str | None = None) -> dict:
    if not isinstance(text, str) or not text.strip() or len(text) > 32768:
        raise LiveSessionError('Message must contain 1–32768 characters')
    if not 0 <= wait <= 30:
        raise LiveSessionError('wait must be between 0 and 30 seconds')
    request_id = _canonical_id(request_id) if request_id else str(uuid4())
    record = _resolve(target)
    if expected_runtime_id is not None and record['runtime_id'] != _canonical_id(expected_runtime_id):
        raise LiveSessionError('Session runtime changed; no message was sent')
    if sender_snapshot is None:
        sender = _sender(sender_session, sender_name)
    else:
        # Owned headless launches retain attribution after the primary exits.
        # This is a captured peer identity, never a live owner-approval token.
        if not isinstance(sender_snapshot, dict) or sender_snapshot.get('session_id') != sender_session:
            raise LiveSessionError('Captured sender does not match the launching session')
        if sender_session is not None:
            _canonical_id(sender_session)
        sender = {'session_id': sender_session, 'attribution': 'captured-at-launch'}
        for key in ('kind', 'agent', 'topic', 'name'):
            value = sender_snapshot.get(key)
            if value is not None:
                if not isinstance(value, str) or len(value) > 200:
                    raise LiveSessionError('Invalid captured sender label')
                sender[key] = value
    if record['session_id'] == sender_session:
        raise LiveSessionError('Use the current conversation directly instead of messaging itself')
    try:
        result = _rpc(record, 'message', request_id=request_id, text=text, sender=sender)
    except (OSError, ValueError) as exc:
        raise LiveSessionError(f'{exc} Request ID: {request_id}') from None
    return result_session(record['session_id'], request_id, wait) if wait else result


def result_session(target: str, request_id: str, wait: float = 0) -> dict:
    request_id = _canonical_id(request_id)
    if not 0 <= wait <= 30:
        raise LiveSessionError('wait must be between 0 and 30 seconds')
    try:
        record = _resolve(target)
        return _rpc(record, 'result', request_id=request_id, wait=wait)
    except LiveSessionError as unavailable:
        # Completed results survive a target exit. Pending records are never
        # automatically replayed to a new process after a crash or reload.
        session_id = _canonical_id(target.removeprefix('@session:'))
        file = runtime_root() / 'messages' / session_id / f'{request_id}.json'
        try:
            request = _read_record(file)
        except (OSError, ValueError):
            raise unavailable
        if request.get('status') in ('queued', 'running'):
            request = {**request, 'status': 'interrupted', 'error': 'The accepting runtime is unavailable. Delivery/result is uncertain; do not automatically resend.'}
        return {'request': request}


def quit_session(target: str, sender_session: str | None = None, confirm_unmanaged: bool = False, *, expected_runtime_id: str | None = None) -> dict:
    record = _resolve(target)
    if expected_runtime_id is not None and record['runtime_id'] != _canonical_id(expected_runtime_id):
        raise LiveSessionError('Session runtime changed; it was not quit')
    _sender(sender_session)
    if sender_session == record['session_id']:
        raise LiveSessionError('Use native /quit for your own session')
    current = _rpc(record, 'inspect')['session']
    if sender_session and current.get('created_by') != sender_session and not confirm_unmanaged:
        raise LiveSessionError('Explicit owner approval is required to quit a session you did not create (confirm_unmanaged)')
    return _rpc(record, 'quit')


def start_session(agent: str | None, topic: str | None, directory: str, session: str | None = None, text: str | None = None, sender_session: str | None = None, provider: str | None = None, model: str | None = None, kind: str = 'pipal') -> dict:
    if kind not in ('pi', 'pipal'):
        raise LiveSessionError('Session kind must be pi or pipal')
    entry = None
    if kind == 'pipal':
        entry = get_agent(agent) if agent else None
        if not entry:
            raise LiveSessionError(f'Unknown registered agent: {agent}')
        topic = validate_topic_name(topic or 'main')
    elif agent or topic:
        raise LiveSessionError('Plain Pi sessions do not have a Pipal agent or topic')
    cwd = Path(directory).expanduser().resolve()
    if not cwd.is_dir():
        raise LiveSessionError('Working directory must exist')
    _sender(sender_session)
    if text is not None and (not text.strip() or len(text) > 32768):
        raise LiveSessionError('Initial message must contain 1–32768 characters')
    tmux = shutil.which('tmux')
    if not tmux:
        raise LiveSessionError('tmux is required to start a handoff-capable session')
    saved = None
    if session:
        from .cli import _resolve_session_file, _session_header
        saved = _resolve_session_file(entry['path'], topic, session) if entry else Path(session).expanduser().resolve()
        if not saved or not saved.is_file():
            raise LiveSessionError('Saved session not found or reference is ambiguous')
        if entry:
            try:
                saved.resolve().relative_to(topic_sessions_dir(entry['path'], topic).resolve())
            except ValueError:
                raise LiveSessionError('Saved session must belong to the selected agent/topic') from None
        if saved.suffix != '.jsonl':
            raise LiveSessionError('Saved session must be a native JSONL conversation')
        header = _session_header(saved)
        if not entry and header.get('type') != 'session':
            raise LiveSessionError('Saved file is not a native Pi conversation')
        native_id = _canonical_id(header.get('id'))
        if any(item['session_id'] == native_id for item in list_sessions()):
            raise LiveSessionError('That conversation is already running; message it instead of creating another writer')
    launch_id = 'pipal-' + uuid4().hex[:16]
    endpoint = str(socket_root() / 'tmux.sock')
    environment = {
        key: os.environ[key] for key in ('HOME', 'PIPAL_HOME', 'PI_CODING_AGENT_DIR', 'PYTHONPATH', 'PATH', 'PI_APP_PORT') if key in os.environ
    }
    environment.update(PIPAL_DISABLE_AUTOGREET='1', PIPAL_MANAGED_TMUX=launch_id, PIPAL_SESSION_CREATOR=sender_session or '')
    # A long-lived tmux server may retain its first caller's delegation/runtime
    # flags. A handoff is a fresh normal conversation, never that caller's child.
    bootstrap = ('import os; '
                 'keep={"PIPAL_HOME","PIPAL_DISABLE_AUTOGREET","PIPAL_MANAGED_TMUX","PIPAL_SESSION_CREATOR"}; '
                 '[os.environ.pop(key, None) for key in list(os.environ) if key.startswith("PIPAL_") and key not in keep]; '
                 'from pipal.cli import main; raise SystemExit(main())')
    if kind == 'pi':
        pi_executable = shutil.which('pi')
        if not pi_executable:
            raise LiveSessionError('Pi must be installed to start a plain Pi session')
        bridge = str(Path(__file__).parent / 'extensions' / 'session_bridge.ts')
        bootstrap = bootstrap.replace('from pipal.cli import main; raise SystemExit(main())',
                                      'import sys; from pipal.runner import _lock_session_for_exec; '
                                      'lock_fd=_lock_session_for_exec(sys.argv[1:]); os.execv(sys.argv[1], sys.argv[1:])')
        launch = [pi_executable, '--extension', bridge]
    else:
        launch = ['agent', 'chat', agent, '--topic', topic]
    command = ['env', *[f'{key}={value}' for key, value in environment.items()], sys.executable, '-c', bootstrap, *launch]
    if saved:
        command += ['--session', str(saved)]
    if provider:
        command += ['--provider', provider]
    if model:
        command += ['--model', model]
    subprocess.run([tmux, '-S', endpoint, 'new-session', '-d', '-s', launch_id, '-c', str(cwd), shlex.join(command)], check=True, capture_output=True, text=True, timeout=10)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        for item in list_sessions():
            if item.get('managed_name') == launch_id:
                result = {'session': item}
                if text:
                    try:
                        result['request'] = message_session(item['session_id'], text, sender_session)['request']
                    except LiveSessionError as exc:
                        # Creation succeeded. Return its identity even if initial
                        # delivery is uncertain; never invite duplicate starts.
                        result['initial_message_error'] = str(exc)
                return result
        # Waiting for a specific subprocess startup, not scheduling agent work.
        time.sleep(0.05)
    subprocess.run([tmux, '-S', endpoint, 'kill-session', '-t', launch_id], capture_output=True, timeout=5)
    raise LiveSessionError('The new session failed to register; its private launch terminal was cleaned up')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='pipal live', description='Discover and communicate with participating Pi and Pipal runtimes')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('list', 'inspect', 'start', 'message', 'result', 'quit', 'attach'):
        command = commands.add_parser(name)
        command.add_argument('--json', action='store_true', help='Machine-readable JSON (also the default)')
        if name not in ('list', 'start'):
            command.add_argument('target')
        if name in ('start', 'message', 'quit'):
            command.add_argument('--sender-session')
        if name in ('message', 'result'):
            command.add_argument('--wait', type=float, default=0)
        if name in ('start', 'message'):
            command.add_argument('--text', required=name == 'message')
        if name == 'message':
            command.add_argument('--request-id')
        if name == 'result':
            command.add_argument('request_id')
        if name == 'quit':
            command.add_argument('--confirm-unmanaged', action='store_true')
        if name == 'start':
            command.add_argument('--kind', choices=('pi', 'pipal'), default='pipal')
            command.add_argument('--agent')
            command.add_argument('--topic')
            command.add_argument('--directory', required=True)
            command.add_argument('--session')
            command.add_argument('--provider')
            command.add_argument('--model')
    args = parser.parse_args(argv)
    try:
        if args.command == 'list':
            result = {'sessions': list_sessions()}
        elif args.command == 'inspect':
            result = {'session': inspect_session(args.target)}
        elif args.command == 'start':
            result = start_session(args.agent, args.topic, args.directory, args.session, args.text, args.sender_session, args.provider, args.model, args.kind)
        elif args.command == 'message':
            result = message_session(args.target, args.text, args.sender_session, args.wait, args.request_id)
        elif args.command == 'result':
            result = result_session(args.target, args.request_id, args.wait)
        elif args.command == 'quit':
            result = quit_session(args.target, args.sender_session, args.confirm_unmanaged)
        else:
            record = inspect_session(args.target)
            if not record.get('managed_name'):
                raise LiveSessionError('This session belongs to its original terminal; no second writer was started')
            os.execvp('tmux', ['tmux', '-S', str(socket_root() / 'tmux.sock'), 'attach-session', '-t', record['managed_name']])
            return 0
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
