"""
End-to-end test: boot a real server on a scratch DB copy, drive the
JSON API over TCP, and verify run_command returns TestBot's output.

This is the regression test for the whole MCP dev loop.
Skipped automatically if mm.db is missing.
"""
import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
GAME_PORT = 7901
API_PORT = 7902
TOKEN = 'integration-test-token'


def _wait_for_port(port, proc, timeout=60.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False  # server died at boot
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


class ApiSocket:
    """Minimal JSON-lines API client for tests."""

    def __init__(self, port, token):
        self.sock = socket.create_connection(('127.0.0.1', port),
                                             timeout=30)
        self.file = self.sock.makefile('r', encoding='utf-8')
        resp = self.call('auth', {'token': token})
        assert resp['ok'], resp

    def call(self, cmd, args=None):
        line = json.dumps({'id': cmd, 'cmd': cmd, 'args': args or {}})
        self.sock.sendall((line + '\n').encode('utf-8'))
        line = self.file.readline()
        assert line, 'server closed connection'
        return json.loads(line)

    def close(self):
        self.sock.close()


@pytest.fixture(scope='module')
def server(tmp_path_factory):
    src = REPO / 'mm.db'
    if not src.exists():
        pytest.skip('mm.db not present')
    scratch = tmp_path_factory.mktemp('db') / 'scratch.db'
    shutil.copy(src, scratch)
    # Copy WAL sidecars if present so recent writes aren't lost
    for suffix in ('-wal', '-shm'):
        side = Path(str(src) + suffix)
        if side.exists():
            shutil.copy(side, str(scratch) + suffix)

    boot_log = scratch.parent / 'server-stdout.log'
    log_fh = open(boot_log, 'w')
    proc = subprocess.Popen(
        [sys.executable, 'megamoo.py', str(scratch),
         '--port', str(GAME_PORT), '--api',
         '--api-port', str(API_PORT), '--api-token', TOKEN],
        cwd=REPO, stdout=log_fh, stderr=subprocess.STDOUT)
    log_fh.close()
    try:
        if not _wait_for_port(API_PORT, proc):
            tail = boot_log.read_text(errors='replace')[-2000:]
            pytest.fail(f'API port never opened. Server output tail:\n{tail}')
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_run_command_look_returns_room_output(server):
    api = ApiSocket(API_PORT, TOKEN)
    try:
        resp = api.call('run_command', {'command': 'look', 'wait': 0.5})
        assert resp['ok'], resp
        output = resp['result']['output']
        assert output.strip(), 'look produced no output'
        # TestBot exists and is somewhere real
        bot = resp['result']['testbot']
        loc = api.call('get_location', {'objnum': bot})
        assert loc['ok'] and loc['result']['location'], loc
    finally:
        api.close()


def test_server_status_reports_running(server):
    api = ApiSocket(API_PORT, TOKEN)
    try:
        resp = api.call('server_status')
        assert resp['ok'], resp
        assert resp['result']['running'] is True
        assert resp['result']['uptime_seconds'] >= 0
    finally:
        api.close()


def test_disconnect_testbot(server):
    api = ApiSocket(API_PORT, TOKEN)
    try:
        api.call('run_command', {'command': 'look', 'wait': 0.1})
        resp = api.call('disconnect_testbot')
        assert resp['ok'] and resp['result']['disconnected'] is True
        # Second disconnect is a no-op, not an error
        resp = api.call('disconnect_testbot')
        assert resp['ok'] and resp['result']['disconnected'] is False
    finally:
        api.close()
