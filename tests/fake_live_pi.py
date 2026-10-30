"""Native RPC/live-protocol fake for transport tests; never calls a provider.

Wrap an existing event-producing fixture as the simulated model execution. Its
work starts only after an actual shared message request arrives on the socket.
"""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
from uuid import uuid4


def wrap_native(path: Path) -> None:
    payload = path.with_name(path.name + '.payload')
    path.replace(payload)
    path.write_text(f'#!{sys.executable}\nimport sys\nsys.path.insert(0, {str(Path(__file__).parent)!r})\nfrom fake_live_pi import serve\nserve({str(payload)!r})\n')
    path.chmod(0o755)


def serve(payload: str) -> None:
    sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
    from pipal import live_sessions as live
    args = sys.argv[1:]
    if os.environ.get('SESSION_TEST_NATIVE_ARGS'):
        Path(os.environ['SESSION_TEST_NATIVE_ARGS']).write_text(json.dumps(args))
    assert args[args.index('--mode') + 1] == 'rpc', args
    session_file = Path(args[args.index('--session') + 1])
    session_file.parent.mkdir(parents=True, exist_ok=True)
    if not session_file.exists():
        session_file.write_text(json.dumps({'type': 'session', 'version': 3, 'id': str(uuid4()), 'cwd': os.getcwd()}) + '\n')
    session_id = json.loads(session_file.read_text().splitlines()[0])['id']
    runtime_id = str(uuid4())
    socket_file = live.socket_root() / (runtime_id + '.sock')
    registry = live._private_dir(live.runtime_root() / 'sessions') / (session_id + '.json')
    messages = live._private_dir(live._private_dir(live.runtime_root() / 'messages') / session_id)
    lock, output_lock = threading.RLock(), threading.Lock()
    state = {'request': None, 'child': None, 'stop': False}

    def emit(event):
        with output_lock:
            print(json.dumps(event), flush=True)

    def save(record):
        file = messages / (record['request_id'] + '.json')
        temp = file.with_suffix('.tmp')
        temp.write_text(json.dumps(record)); temp.chmod(0o600); temp.replace(file)

    def metadata():
        return {'protocol': 1, 'session_id': session_id, 'reference': '@session:' + session_id,
                'runtime_id': runtime_id, 'pid': os.getpid(), 'session_file': str(session_file.resolve()),
                'kind': 'pipal' if os.environ.get('PIPAL_AGENT_DIR') else 'pi', 'execution': 'headless',
                'agent': Path(os.environ.get('PIPAL_AGENT_DIR', '')).name, 'topic': os.environ.get('PIPAL_TOPIC', ''),
                'directory': os.getcwd(), 'busy': bool(state['child'] and state['child'].poll() is None), 'pending': 0}

    def execute(record):
        peer_message = {'role': 'custom', 'customType': 'pipal-session-message', 'content': record['text'], 'details': {'request_id': record['request_id']}}
        emit({'type': 'message_start', 'message': peer_message})
        emit({'type': 'message_end', 'message': peer_message})
        child = subprocess.Popen([payload, *args, '-p', record['text']], stdout=subprocess.PIPE, text=True)
        with lock:
            state['child'] = child
            record['status'] = 'running'; save(record)
        reply = ''
        for line in child.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                print(line.rstrip(), file=sys.stderr, flush=True); continue
            emit(event)
            message = event.get('message', {})
            if event.get('type') == 'message_end' and message.get('role') == 'assistant':
                reply = '\n'.join(p.get('text', '') for p in message.get('content', []) if p.get('type') == 'text') or reply
        child.wait(); child.stdout.close()
        with lock:
            record.update(status='completed' if child.returncode == 0 else 'failed', reply=reply)
            if child.returncode:
                record['error'] = f'Fixture model exited {child.returncode}'
            save(record)
        emit({'type': 'agent_settled'})

    server = socket.socket(socket.AF_UNIX); server.bind(str(socket_file)); socket_file.chmod(0o600); server.listen()
    registry.write_text(json.dumps({**metadata(), '_socket': str(socket_file)})); registry.chmod(0o600)

    def accept():
        while not state['stop']:
            try:
                peer, _ = server.accept()
            except OSError:
                break
            with peer:
                data = b''
                while b'\n' not in data:
                    chunk = peer.recv(65536)
                    if not chunk: break
                    data += chunk
                if not data: continue
                request = json.loads(data.split(b'\n')[0])
                with lock:
                    assert request['session_id'] == session_id and request['runtime_id'] == runtime_id
                    op = request['op']
                    if op == 'inspect':
                        result = {'session': metadata()}
                    elif op == 'message':
                        assert request['request_id'] == os.environ['PIPAL_SESSION_INITIAL_REQUEST']
                        if state['request'] is None:
                            record = {'request_id': request['request_id'], 'session_id': session_id, 'runtime_id': runtime_id,
                                      'sender': request['sender'], 'sender_session_id': request['sender']['session_id'],
                                      'text': request['text'], 'reply': '', 'status': 'queued'}
                            state['request'] = record; save(record)
                            threading.Thread(target=execute, args=(record,), daemon=True).start()
                        result = {'request': state['request']}
                    elif op == 'result':
                        result = {'request': json.loads((messages / (request['request_id'] + '.json')).read_text())}
                    elif op == 'quit':
                        if metadata()['busy']:
                            result = {'error': 'Session is busy or has queued work'}
                        else:
                            state['stop'] = True; result = {'accepted': True, 'session_id': session_id}
                    else:
                        result = {'error': 'Unknown operation'}
                    peer.sendall((json.dumps(result) + '\n').encode())
    threading.Thread(target=accept, daemon=True).start()

    def cancel(_signal, _frame):
        raise SystemExit(130)
    signal.signal(signal.SIGTERM, cancel)
    signal.signal(signal.SIGINT, cancel)
    try:
        for line in sys.stdin:
            request = json.loads(line)
            if request.get('type') == 'get_state':
                emit({'type': 'response', 'id': request.get('id'), 'command': 'get_state', 'success': True, 'data': {'sessionId': session_id}})
            elif request.get('type') == 'abort' and state['child']:
                state['child'].terminate()
            if state['stop']: break
    finally:
        state['stop'] = True
        if state['child'] and state['child'].poll() is None:
            state['child'].terminate(); state['child'].wait(timeout=2)
        record = state['request']
        if record and record['status'] not in ('completed', 'failed'):
            record.update(status='interrupted', error='Fixture runtime stopped'); save(record)
        registry.unlink(missing_ok=True); server.close(); socket_file.unlink(missing_ok=True)


if __name__ == '__main__':
    assert sys.argv[1] == '--wrap'
    wrap_native(Path(sys.argv[2]))
