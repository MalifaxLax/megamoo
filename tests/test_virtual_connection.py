"""Unit tests for moo/virtual_connection.py — output capture for TestBot."""
import asyncio

from moo.virtual_connection import VirtualConnection


def make_conn():
    # server/player_obj are only stored, never touched by capture logic
    return VirtualConnection(server=None, player_obj=None)


def test_queue_message_captures_text():
    conn = make_conn()
    conn.queue_message("Hello, world.")
    assert conn.drain() == "Hello, world."


def test_queue_message_strips_color_tags():
    conn = make_conn()
    conn.queue_message("%<245>dim chrome%n normal")
    out = conn.drain()
    assert "%<245>" not in out
    assert "%n" not in out
    assert "dim chrome" in out and "normal" in out


def test_queue_message_strips_raw_ansi():
    """Verbs sometimes emit pre-rendered ANSI escapes, not MOO tags."""
    conn = make_conn()
    conn.queue_message("exits: \x1b[38;5;245msouth\x1b[0m done")
    out = conn.drain()
    assert "\x1b" not in out
    assert "south" in out and "done" in out


def test_drain_clears_buffer():
    conn = make_conn()
    conn.queue_message("first")
    conn.drain()
    assert conn.drain() == ""


def test_drain_joins_messages_in_order():
    conn = make_conn()
    conn.queue_message("one")
    conn.queue_message("two")
    assert conn.drain() == "one\ntwo"


def test_send_is_async_and_captures():
    conn = make_conn()
    asyncio.run(conn.send("via send"))
    assert conn.drain() == "via send"


def test_messaging_attrs_present():
    """Attributes the game's messaging path reads via getattr/hasattr."""
    conn = make_conn()
    assert conn.color_enabled is False
    assert conn.protocols == set()
    assert conn.authenticated is True
    assert conn._interactive_session is None
    assert not hasattr(conn, 'send_gmcp_sync')  # GMCP path must skip us
