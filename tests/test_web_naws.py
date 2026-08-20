"""tests/test_web_naws.py — the size a browser reports for itself.

A web client measures its own scrollback and sends the result, which is
how a screen drawn in columns learns what it has to work with.  The
number arrives from the browser, so it is input: these pin the range that
is accepted and, more importantly, that anything outside it leaves the
last good size standing rather than replacing it with a width no screen
can be drawn in.
"""
import pytest

from moo.web.connection import WebSocketConnection


class _Writer:
    """Enough of an asyncio writer for the constructor."""

    def get_extra_info(self, _name):
        return ('127.0.0.1', 54321)


@pytest.fixture
def conn():
    return WebSocketConnection(reader=None, writer=_Writer(), server=None)


def test_a_client_that_never_reports_keeps_the_default(conn):
    assert conn.width == 120
    assert conn.height == 50


def test_a_reported_size_replaces_the_default(conn):
    conn._set_naws({'type': 'naws', 'width': 117, 'height': 44})
    assert (conn.width, conn.height) == (117, 44)


def test_strings_are_accepted_as_the_numbers_they_spell(conn):
    # JSON from a hand-rolled client may quote them.
    conn._set_naws({'width': '104', 'height': '30'})
    assert (conn.width, conn.height) == (104, 30)


@pytest.mark.parametrize('bad', [
    {'width': 19, 'height': 44},          # narrower than any screen drawn
    {'width': 501, 'height': 44},         # wider than any real terminal
    {'width': 117, 'height': 4},          # too few rows to be a window
    {'width': 117, 'height': 501},
    {'width': 0, 'height': 0},
    {'width': -117, 'height': -44},
    {'width': 'wide', 'height': 'tall'},  # not numbers at all
    {'width': None, 'height': None},
    {'height': 44},                       # width missing
    {},                                   # both missing
])
def test_an_unusable_size_is_ignored_rather_than_stored(conn, bad):
    conn._set_naws({'width': 117, 'height': 44})   # a good size first
    conn._set_naws(bad)
    assert (conn.width, conn.height) == (117, 44), (
        'a bad report must leave the last good size standing')


def test_the_bounds_themselves_are_accepted(conn):
    conn._set_naws({'width': 20, 'height': 5})
    assert (conn.width, conn.height) == (20, 5)
    conn._set_naws({'width': 500, 'height': 500})
    assert (conn.width, conn.height) == (500, 500)


def test_a_float_width_is_taken_as_its_whole_number(conn):
    # devicePixelRatio arithmetic in the client can yield 116.9997.
    conn._set_naws({'width': 116.9997, 'height': 44.2})
    assert (conn.width, conn.height) == (116, 44)
