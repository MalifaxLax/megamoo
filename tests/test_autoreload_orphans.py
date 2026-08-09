"""The verb watcher's seed scan, where the verb tree and the world disagree.

A world under development grows verb directories for objects that do not
exist yet -- you sketch ``verbs/900/`` before you build #900.  The watcher
has to say so once, not once per file, and it must not let that swallow the
per-file failures that a developer actually acts on.

``_watch_verbs`` is driven directly on a duck-typed stand-in: the seed scan
is the whole subject, so the loop is stopped before its first sleep.
"""
import asyncio
import logging
import os
from types import SimpleNamespace

from moo import verb_loader
from moo.server import MegaMOOServer


class _FakeDatabase:
    """Answers ``get_object`` for a fixed set of objects, KeyError otherwise.

    Mirrors the real contract: :meth:`moo.database.MOODatabase.get_object`
    raises ``KeyError`` for an object that does not exist -- it never
    returns ``None`` -- which is exactly what the watcher has to classify.
    """

    def __init__(self, objects):
        self._objects = objects

    def get_object(self, objnum):
        try:
            return self._objects[objnum]
        except KeyError:
            raise KeyError(objnum)


def _fake_object(verbs=()):
    return SimpleNamespace(verbs=list(verbs))


def _write_verb(base, objnum, name, code='def x(): pass\n'):
    d = os.path.join(base, str(objnum))
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f'{name}.py')
    with open(path, 'w') as f:
        f.write(code)
    return path


def _run_seed(tmp_path, database, monkeypatch):
    """Run _watch_verbs far enough to finish seeding, then stop it."""
    monkeypatch.setattr(verb_loader, 'resolve_verb_base_path',
                        lambda db: str(tmp_path))
    server = SimpleNamespace(
        config=SimpleNamespace(dev=SimpleNamespace(autoreload_interval=0.01)),
        database=database,
        # Stops the poll loop before its first sleep: the seed scan runs to
        # completion regardless, since it happens before the loop is entered.
        state=SimpleNamespace(running=False),
    )
    asyncio.run(MegaMOOServer._watch_verbs(server))


def test_missing_objects_collapse_to_one_line(tmp_path, monkeypatch, caplog):
    """Eleven files across five absent objects: one warning, five numbers."""
    for objnum, count in ((510, 2), (800, 3), (801, 1), (900, 4), (5089, 1)):
        for i in range(count):
            _write_verb(tmp_path, objnum, f'v{i}')

    with caplog.at_level(logging.WARNING, logger='megamoo.server'):
        _run_seed(tmp_path, _FakeDatabase({}), monkeypatch)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1, [r.getMessage() for r in warnings]

    message = warnings[0].getMessage()
    assert 'ignoring 11 verb file(s) for 5 object(s)' in message
    # Sorted numerically, not as strings -- #5089 sorts last, not after #510.
    assert '#510, #800, #801, #900, #5089' in message


def test_long_orphan_list_is_truncated(tmp_path, monkeypatch, caplog):
    """A world with many unbuilt objects still gets one readable line."""
    for objnum in range(600, 614):        # 14 objects, one file each
        _write_verb(tmp_path, objnum, 'v')

    with caplog.at_level(logging.WARNING, logger='megamoo.server'):
        _run_seed(tmp_path, _FakeDatabase({}), monkeypatch)

    message = caplog.records[-1].getMessage()
    assert 'ignoring 14 verb file(s) for 14 object(s)' in message
    assert '#609' in message and '#610' not in message
    assert 'and 4 more' in message


def test_real_failures_stay_per_file(tmp_path, monkeypatch, caplog):
    """A missing object must not mask a file that fails on its own merits.

    The object exists, so this is not an orphan -- it is a broken file, and
    the developer needs its path.  Collapsing by cause only works if the
    other causes keep reporting individually.
    """
    _write_verb(tmp_path, 900, 'unbuilt')          # object absent
    bad = _write_verb(tmp_path, 3, 'broken')       # object present, load fails

    def _explode(obj, verb_name, code, *, create=True):
        raise RuntimeError('boom')

    monkeypatch.setattr(verb_loader, 'reload_verb_code', _explode)

    with caplog.at_level(logging.WARNING, logger='megamoo.server'):
        _run_seed(tmp_path, _FakeDatabase({3: _fake_object()}), monkeypatch)

    messages = [r.getMessage() for r in caplog.records
                if r.levelno == logging.WARNING]
    assert any(bad in m and 'boom' in m for m in messages)
    assert any('not in this world: #900' in m for m in messages)
    assert len(messages) == 2


def test_silent_when_every_object_exists(tmp_path, monkeypatch, caplog):
    """The common case -- a healthy world -- warns about nothing."""
    _write_verb(tmp_path, 3, 'look')
    monkeypatch.setattr(verb_loader, 'reload_verb_code',
                        lambda obj, name, code, create=True: 'created')

    with caplog.at_level(logging.WARNING, logger='megamoo.server'):
        _run_seed(tmp_path, _FakeDatabase({3: _fake_object()}), monkeypatch)

    assert [r.getMessage() for r in caplog.records
            if r.levelno == logging.WARNING] == []
