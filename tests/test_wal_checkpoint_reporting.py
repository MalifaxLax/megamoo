"""A checkpoint that was refused must not report success.

On 2026-08-22 a restart came back serving a two-day-old world.  Nothing in
the log looked wrong: the shutdown saved, ``Database closed`` was logged, the
server came up and loaded.  What the log did say, two lines earlier, was
``Timed out stopping API server`` and ``Timed out stopping WebSocket server``
-- and a connection that outlives its server still holds a TRUNCATE
checkpoint off.

``PRAGMA wal_checkpoint`` does not raise when it is refused.  It answers
``(busy, log_frames, frames_folded)`` and sets ``busy=1``.  The old code ran
the pragma inside a ``try``, discarded the result row, and returned ``True``
for anything that did not throw -- so "a reader blocked me and the world is
still in the sidecar" and "the .db on disk is now the world" were the same
answer.  The caller before ``os.execv`` believed the second one.

These tests pin the distinction.  They are not about speed or about WAL
mechanics; they are about a function being able to say no.
"""
import sqlite3

import pytest

from moo.database import Database


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / 'wal.db'), mode='create')
    d.load()
    d.create_object()
    d.save()
    yield d
    try:
        d.close()
    except Exception:
        pass


def _has_wal(db) -> bool:
    mode = db._conn.execute("PRAGMA journal_mode").fetchone()[0]
    return str(mode).lower() == 'wal'


def test_a_reader_holding_the_log_open_is_reported_as_failure(db, tmp_path):
    if not _has_wal(db):
        pytest.skip("database is not journalling in WAL mode")

    # Write enough to put frames in the sidecar worth folding back.
    for _ in range(25):
        db.create_object()
    db.save()

    reader = sqlite3.connect(str(tmp_path / 'wal.db'))
    reader.execute("BEGIN")
    reader.execute("SELECT COUNT(*) FROM objects").fetchone()
    try:
        assert db.checkpoint_wal() is False, (
            "a checkpoint a reader refused was reported as having run"
        )
    finally:
        reader.close()


def test_it_succeeds_once_the_reader_lets_go(db, tmp_path):
    if not _has_wal(db):
        pytest.skip("database is not journalling in WAL mode")

    for _ in range(25):
        db.create_object()
    db.save()

    reader = sqlite3.connect(str(tmp_path / 'wal.db'))
    reader.execute("BEGIN")
    reader.execute("SELECT COUNT(*) FROM objects").fetchone()
    blocked = db.checkpoint_wal()
    reader.close()

    assert blocked is False
    assert db.checkpoint_wal() is True


def test_no_connection_is_a_failure_not_a_crash(db):
    db.close()
    assert db.checkpoint_wal() is False
