"""
Tests for slow work handed off the verb thread.

The property that matters most here is not that a request succeeds -- it is
that a *response never becomes code*.  A model's output, or a hostile
endpoint's, travels into a verb namespace as a value; if it were ever
interpolated into the delivering code string, any of it could execute.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from moo import async_io


# --------------------------------------------------------------------------
# A local endpoint, so nothing here touches the network
# --------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    def _reply(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == '/slow':
            time.sleep(0.4)
            return self._reply(200, {'said': 'eventually'})
        if self.path == '/boom':
            return self._reply(500, {'oh': 'dear'})
        return self._reply(200, {'said': 'hello'})

    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(n) or b'{}')
        self._reply(200, {'echo': body.get('prompt', '')})

    def log_message(self, *a):
        pass


@pytest.fixture(scope='module')
def server():
    srv = HTTPServer(('127.0.0.1', 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{srv.server_port}'
    srv.shutdown()


# --------------------------------------------------------------------------
# http_fetch
# --------------------------------------------------------------------------

def test_fetches_and_reports_success(server):
    r = async_io.http_fetch(server + '/')
    assert r['ok'] is True
    assert r['status'] == 200
    assert json.loads(r['body'])['said'] == 'hello'
    assert r['error'] == ''


def test_posts_json_and_sets_the_content_type(server):
    r = async_io.http_fetch(server + '/', method='POST',
                            data={'prompt': 'knock knock'})
    assert json.loads(r['body'])['echo'] == 'knock knock'


def test_http_error_is_a_result_not_an_exception(server):
    r = async_io.http_fetch(server + '/boom')
    assert r['ok'] is False
    assert r['status'] == 500
    assert 'HTTP 500' in r['error']


def test_unreachable_host_is_a_result_not_an_exception():
    # The caller is a verb that already returned; there is nowhere to
    # catch an exception, so failures must arrive as data.
    r = async_io.http_fetch('http://127.0.0.1:1/nope', timeout=1)
    assert r['ok'] is False
    assert r['status'] == 0
    assert r['error']


def test_timeout_is_a_result_not_an_exception(server):
    r = async_io.http_fetch(server + '/slow', timeout=0.05)
    assert r['ok'] is False
    assert r['error']


# --------------------------------------------------------------------------
# Delivery
# --------------------------------------------------------------------------

class _FakeTask:
    def __init__(self, ctx):
        self.context = ctx
        self.task_id = 1
        self.suspended_until = 0

    def suspend(self, seconds):
        self.suspended_until = time.time() + seconds


class _FakeQueue:
    def __init__(self):
        self.lock = threading.Lock()
        self.suspended_tasks = {}


@pytest.fixture
def captured(monkeypatch):
    """Capture the task _deliver would queue, without a running server."""
    q = _FakeQueue()
    monkeypatch.setattr('moo.tasks.get_task_queue', lambda: q)
    monkeypatch.setattr('moo.tasks.Task', _FakeTask)
    monkeypatch.setattr('moo.tasks.TaskContext',
                        lambda **kw: type('C', (), kw)())
    monkeypatch.setattr('moo.builtins.make_call_verb',
                        lambda pobj, db, _depth=0: (lambda *a, **k: None))
    return q


class _Obj:
    objnum = 42


def _wait_for(q, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if q.suspended_tasks:
            return next(iter(q.suspended_tasks.values()))
        time.sleep(0.01)
    raise AssertionError("nothing was delivered")


def test_result_is_delivered_to_the_reply_verb(captured):
    async_io.submit(lambda: {'ok': True, 'status': 200,
                             'body': 'hi', 'error': ''},
                    on=_Obj(), reply='heard', tag='t1')
    task = _wait_for(captured)
    ctx = task.delayed_context
    assert ctx['_reply'] == 'heard'
    assert ctx['_ok'] is True
    assert ctx['_body'] == 'hi'
    assert ctx['_tag'] == 't1'


def test_work_that_raises_is_delivered_as_a_failure(captured):
    def explode():
        raise RuntimeError("model is on fire")

    async_io.submit(explode, on=_Obj(), reply='heard')
    task = _wait_for(captured)
    assert task.delayed_context['_ok'] is False
    assert 'on fire' in task.delayed_context['_error']


def test_the_response_never_becomes_code(captured):
    # The single most important property: a body that is valid Python must
    # not appear anywhere in the string that gets compiled.
    evil = "'; import os; os.system('rm -rf /'); x = '"
    async_io.submit(lambda: {'ok': True, 'status': 200,
                             'body': evil, 'error': ''},
                    on=_Obj(), reply='heard')
    task = _wait_for(captured)

    assert evil not in task.delayed_code
    assert 'import os' not in task.delayed_code
    # It is present as a value, which is the whole point.
    assert task.delayed_context['_body'] == evil


def test_delivery_namespace_carries_call_verb(captured):
    # Built from scratch rather than inherited from a calling verb, so it
    # has to bring its own.
    async_io.submit(lambda: {'ok': True, 'status': 200, 'body': '', 'error': ''},
                    on=_Obj(), reply='heard')
    task = _wait_for(captured)
    assert callable(task.delayed_context['call_verb'])


def test_tag_survives_untouched(captured):
    tag = {'player': 7, 'topic': 'weather'}
    async_io.submit(lambda: {'ok': True, 'status': 200, 'body': '', 'error': ''},
                    on=_Obj(), reply='heard', tag=tag)
    assert _wait_for(captured).delayed_context['_tag'] == tag


# --------------------------------------------------------------------------
# The builtin
# --------------------------------------------------------------------------

def test_request_requires_somewhere_to_send_the_answer():
    from moo.builtins import request
    with pytest.raises(ValueError, match='reply='):
        request('http://example.invalid', reply='')


def test_request_requires_an_object_to_answer_on():
    from moo.builtins import request
    with pytest.raises(ValueError, match='on='):
        request('http://example.invalid', reply='heard')
