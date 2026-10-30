"""Bounded headless backend for the shared live-session primitives.

A native RPC process remains the only session writer. Requests/replies go through
live_sessions, not a second delegation transport. RPC stdin is used only for
read-only state heartbeats and owned-process shutdown, never prompt delivery.
"""
from __future__ import annotations

import codecs
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time
from typing import Callable, Iterator
from uuid import uuid4

from . import live_sessions as live
from .runner import _lock_session_for_exec


def run_session(spec: dict, on_process: Callable | None = None) -> Iterator[dict]:
    """Stream one request's native events and a durable session_result reference.

    Additional accepted peer requests drain within the existing process budget;
    they never become this request's output or extend its lifetime indefinitely.
    Only this function's own child may be aborted/terminated during cleanup.
    """
    cwd = Path(spec['directory']).expanduser().resolve()
    session_file = Path(spec['session_file']).expanduser().resolve()
    if not cwd.is_dir() or session_file.suffix != '.jsonl':
        raise ValueError('A working directory and native JSONL session path are required')
    text = spec['text']
    if not isinstance(text, str) or not text.strip() or len(text) > 32768:
        raise ValueError('Request must contain 1–32768 characters')
    timeout = float(spec.get('timeout_seconds', 300))
    if not 0 < timeout <= 86400:
        raise ValueError('Session timeout must be 0–86400 seconds')
    request_id = str(uuid4())
    args = [spec['native_pi'], '--mode', 'rpc', '--session', str(session_file),
            '--extension', str(Path(__file__).parent / 'extensions/session_bridge.ts')]
    for field, flag in [('prompt_file', '--append-system-prompt'), ('provider', '--provider'), ('model', '--model')]:
        if spec.get(field):
            args += [flag, str(spec[field])]
    env = {key: value for key, value in os.environ.items() if not key.startswith('PIPAL_') or key == 'PIPAL_HOME'}
    env.update(PIPAL_DISABLE_AUTOGREET='1', PIPAL_SESSION_EXECUTION='headless', PIPAL_SESSION_INITIAL_REQUEST=request_id)
    if spec.get('agent_directory'):
        env.update(PIPAL_AGENT_DIR=str(spec['agent_directory']), PIPAL_TOPIC=spec.get('topic') or 'main')
    if spec.get('sender_session'):
        env['PIPAL_SESSION_CREATOR'] = live._canonical_id(spec['sender_session'])
    try:
        lock_fd = _lock_session_for_exec(args)
    except SystemExit:
        raise RuntimeError('Native conversation is already active; no second writer was started') from None
    proc = None
    selector = selectors.DefaultSelector()
    buffers, decoders, diagnostic = {}, {}, []
    deadline = time.monotonic() + timeout
    target = None
    final_text = ''
    started = False
    settled = False
    outcome = None
    returned = False

    def heartbeat():
        if proc and proc.poll() is None and proc.stdin and not proc.stdin.closed:
            try:
                proc.stdin.write(b'{"type":"get_state","id":"session-worker-state"}\n')
                proc.stdin.flush()
            except (OSError, ValueError):
                pass

    def read_events(wait: float):
        events = []
        for key, _ in selector.select(wait):
            chunk = os.read(key.fd, 65536)
            if not chunk:
                selector.unregister(key.fileobj)
            data = decoders[key.fd].decode(chunk, final=not chunk)
            buffer = buffers[key.fd] + data
            lines = buffer.split('\n')
            tail = lines.pop()
            buffers[key.fd] = tail if chunk else ''
            if not chunk and tail:
                lines.append(tail)
            if len(buffers[key.fd]) > 16 * 1024 * 1024:
                raise RuntimeError('Native session output exceeded the frame limit')
            for line in lines:
                if key.fileobj is proc.stderr:
                    if line.strip():
                        diagnostic.append(line[-2000:]); del diagnostic[:-10]
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    if line.strip():
                        diagnostic.append(line[-2000:]); del diagnostic[:-10]
                    continue
                if isinstance(event, dict):
                    events.append(event)
                    if event.get('type') == 'extension_ui_request' and event.get('method') in ('confirm', 'select', 'input', 'editor'):
                        # A headless worker cannot manufacture human approval.
                        response = {'type': 'extension_ui_response', 'id': event['id'], 'cancelled': True}
                        try:
                            proc.stdin.write((json.dumps(response) + '\n').encode()); proc.stdin.flush()
                        except (OSError, ValueError):
                            pass  # An exiting child cannot accept approval either.
                        events.append({'type': 'session_ui_denied', 'id': event['id'], 'method': event['method'], 'reason': 'Headless work cannot approve actions; return a blocker to the owner'})
        return events

    try:
        if live.list_sessions(session_file=session_file):
            raise RuntimeError('Native conversation is already active; no second writer was started')
        proc = subprocess.Popen(args, cwd=str(cwd), env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                pass_fds=(lock_fd,) if lock_fd is not None else ())
        if on_process:
            on_process(proc)
        for stream in (proc.stdout, proc.stderr):
            selector.register(stream, selectors.EVENT_READ)
            buffers[stream.fileno()] = ''
            decoders[stream.fileno()] = codecs.getincrementaldecoder('utf-8')('replace')
        startup_deadline = min(deadline, time.monotonic() + 20)
        while time.monotonic() < startup_deadline and proc.poll() is None:
            read_events(0.03)
            target = next(iter(live.list_sessions(pid=proc.pid, session_file=session_file)), None)
            if target:
                break
        if not target:
            raise RuntimeError('Headless session failed to register' + (': ' + '\n'.join(diagnostic) if diagnostic else ''))
        # Persist the reference before attempting delivery, including uncertain ACKs.
        yield {'type': 'session_request_started', 'session': target, 'request_id': request_id}
        live.message_session(target['session_id'], text, spec.get('sender_session'), request_id=request_id,
                             sender_name=spec.get('sender_name'), sender_snapshot=spec.get('sender_snapshot'), expected_runtime_id=target['runtime_id'])
        next_poll = 0.0
        while True:
            events = read_events(0.05)
            for event in events:
                if event.get('type') == 'response':
                    continue
                message = event.get('message') if isinstance(event.get('message'), dict) else {}
                if message.get('role') == 'custom' and message.get('customType') == 'pipal-session-message' and message.get('details', {}).get('request_id') == request_id:
                    started = True
                if started and not settled:
                    if event.get('type') == 'message_end' and message.get('role') == 'assistant':
                        value = '\n'.join(part.get('text', '') for part in message.get('content', []) if part.get('type') == 'text').strip()
                        final_text = value or final_text
                    yield event
                    if event.get('type') == 'agent_settled':
                        settled = True
            now = time.monotonic()
            if now >= next_poll:
                next_poll = now + 0.1
                outcome = live.result_session(target['session_id'], request_id)['request']
                if outcome.get('status') in ('failed', 'cancelled', 'interrupted'):
                    raise RuntimeError(outcome.get('error') or f"Session request {outcome['status']}")
                if outcome.get('status') == 'completed' and settled:
                    if not returned:
                        yield {'type': 'session_result', 'request': outcome, 'final_text': final_text or outcome.get('reply', '')}
                        returned = True
                    try:
                        live.quit_session(target['session_id'], expected_runtime_id=target['runtime_id'])
                        heartbeat()
                        break
                    except live.LiveSessionError as exc:
                        if 'Session not running' in str(exc) or 'Session runtime changed' in str(exc):
                            break
                        if 'busy or has queued work' not in str(exc):
                            raise
            if now >= deadline:
                if returned:
                    break  # Original request succeeded; bounded peer cleanup only.
                raise TimeoutError(f'Headless session timed out after {timeout:g}s · request {request_id}')
            if proc.poll() is not None:
                # Read remaining frames, then consult the durable request rather
                # than interpreting an exit code alone as successful generation.
                for event in read_events(0):
                    if started and not settled and event.get('type') != 'response':
                        yield event
                if returned:
                    break
                raise RuntimeError('Native session exited before completing its request' + (': ' + '\n'.join(diagnostic) if diagnostic else ''))
    finally:
        if proc:
            if proc.poll() is None and proc.stdin:
                try:
                    if not returned:
                        proc.stdin.write(b'{"type":"abort"}\n'); proc.stdin.flush()
                    proc.stdin.close()  # Native RPC disposes extensions on EOF.
                except (OSError, ValueError):
                    pass
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait(timeout=2)
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream:
                    stream.close()
        selector.close()
        if lock_fd is not None:
            os.close(lock_fd)


def main() -> int:
    def cancelled(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, cancelled)
    signal.signal(signal.SIGINT, cancelled)
    try:
        spec = json.loads(sys.stdin.readline(1024 * 1024))
        for event in run_session(spec):
            print(json.dumps(event, ensure_ascii=False), flush=True)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
