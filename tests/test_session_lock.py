"""A resumed Pipal session must have only one active writer."""
import os
import subprocess
import sys

import pytest

from pipal.runner import _lock_session_for_exec


def test_lock_survives_exec_and_releases_on_exit(tmp_path):
    session = tmp_path / "conversation.jsonl"
    session.write_text('{"type":"session","version":3,"id":"test"}\n')
    cmd = ["pi", "--session", str(session)]
    code = (
        "import os, sys\n"
        "from pipal.runner import _lock_session_for_exec\n"
        "_lock_session_for_exec(['pi', '--session', sys.argv[1]])\n"
        "print('locked', flush=True)\n"
        "os.execv('/bin/cat', ['cat'])\n"
    )
    process = subprocess.Popen([sys.executable, "-c", code, str(session)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == "locked"
        with pytest.raises(SystemExit) as conflict:
            _lock_session_for_exec(cmd)
        assert conflict.value.code == 2
    finally:
        process.stdin.close()
        process.wait(timeout=5)
        assert process.returncode == 0, process.stderr.read()
        process.stdout.close()
        process.stderr.close()
    fd = _lock_session_for_exec(cmd)
    assert fd is not None and os.get_inheritable(fd)
    os.close(fd)


def test_no_session_needs_no_lock():
    assert _lock_session_for_exec(["pi", "--no-session"]) is None
