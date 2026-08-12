"""The shipped starter world must agree with its own verb files.

A world created by `megamoo init` announces the disagreement itself, on
its very first boot:

    [autoreload] refreshed 3 verb(s) whose file had changed while the
    server was down

...which for a world thirty seconds old is a claim that cannot be true.
That is how the duplicate `in` alias on the compass verb was found, and
0.7.1 shipped a worse version of the same thing: a fixed database beside
a stale verb file, where the watcher reverted the fix on first start.

This asserts it with **the server's own comparison**, `_verb_matches_file`,
rather than a hand-written one. The check that shipped the compass bug
compared verb *code* and passed, because the code was identical -- the
names disagreed. Any check that is not literally the server's will drift
away from it again, so this imports the real thing.
"""
import json
import pathlib
import sqlite3

import pytest

from moo.server import _verb_matches_file

STARTER = pathlib.Path(__file__).resolve().parent.parent / 'moo' / 'templates' / 'starter'


class _StoredVerb:
    """The shape `_verb_matches_file` reads, built from a database row."""

    def __init__(self, names, code, perms, min_lengths, hidden):
        self.names = names
        self.code = code
        self.perms = perms
        self.min_lengths = min_lengths
        self.hidden = hidden


def _stored_verbs():
    db = sqlite3.connect(STARTER / 'world.db')
    try:
        out = {}
        for objnum, names, code, perms, min_lengths, hidden in db.execute(
                'SELECT objnum, names, code, perms, min_lengths, hidden '
                'FROM verbs'):
            parsed = json.loads(names)
            verb = _StoredVerb(parsed, code, perms,
                               json.loads(min_lengths or '{}'), bool(hidden))
            for name in parsed:
                out[(objnum, name)] = verb
        return out
    finally:
        db.close()


@pytest.mark.skipif(not (STARTER / 'world.db').is_file(),
                    reason='starter template not present')
def test_no_shipped_verb_disagrees_with_its_file():
    stored = _stored_verbs()
    drift = []
    for path in sorted((STARTER / 'verbs').rglob('*.py')):
        try:
            objnum = int(path.parent.name)
        except ValueError:
            continue
        verb = stored.get((objnum, path.stem))
        if verb is None:
            drift.append(f'{objnum}/{path.stem}: no such verb in world.db')
            continue
        if not _verb_matches_file(verb, path.read_text(), path.stem):
            drift.append(f'{objnum}/{path.stem}')
    assert not drift, (
        'these ship disagreeing with world.db, so a new world rewrites them '
        'on first boot: ' + ', '.join(drift))


@pytest.mark.skipif(not (STARTER / 'world.db').is_file(),
                    reason='starter template not present')
def test_the_check_would_notice_a_metadata_only_difference():
    """The bug that got through changed names alone, not code.

    Guards the guard: if this ever passes a verb whose aliases differ while
    its body matches, the check above is worthless in exactly the way its
    predecessor was.
    """
    stored = _stored_verbs()
    (objnum, name), verb = next(iter(stored.items()))
    code = verb.code or ''
    assert _verb_matches_file(verb, code, name)

    tampered = _StoredVerb(list(verb.names) + ['a_name_the_file_never_declares'],
                           code, verb.perms, verb.min_lengths, verb.hidden)
    assert not _verb_matches_file(tampered, code, name), (
        'a names-only difference must be caught; code equality is not enough')


@pytest.mark.skipif(not (STARTER / 'world.db').is_file(),
                    reason='starter template not present')
def test_no_shipped_verb_stores_the_wrong_auth_level():
    """`_verb_matches_file` does not compare auth, so this does.

    The level decides whether `help` lists a command for you, so a verb
    stored at 0 whose body refuses anyone under gm3 is advertised to
    players who cannot run it -- and lands in the wrong section of the
    help listing. @vfind shipped that way for exactly one build.
    """
    from moo.verb_loader import auth_level_required
    db = sqlite3.connect(STARTER / 'world.db')
    try:
        wrong = []
        for path in sorted((STARTER / 'verbs').rglob('*.py')):
            try:
                objnum = int(path.parent.name)
            except ValueError:
                continue
            row = db.execute(
                'SELECT auth FROM verbs WHERE objnum=? AND names LIKE ?',
                (objnum, f'%"{path.stem}"%')).fetchone()
            if row is None:
                continue
            declared = auth_level_required(path.read_text())
            if row[0] != declared:
                wrong.append(f'{objnum}/{path.stem}: stored {row[0]}, '
                             f'file declares {declared}')
        assert not wrong, '; '.join(wrong)
    finally:
        db.close()


@pytest.mark.skipif(not (STARTER / 'world.db').is_file(),
                    reason='starter template not present')
def test_no_shipped_verb_is_missing_its_file():
    """Every verb in world.db has a file, which is the other direction.

    The test above walks files and asks whether the database agrees. It
    cannot see a verb that exists *only* in the database -- and that is
    the drift this repository keeps meeting, most recently in @adalias,
    which added a name to the stored verb and not to the file, so the
    name lasted exactly until the next reload.

    A verb with no file is worse than out of date: it is not in git, an
    editor cannot open it, and `megamoo init` ships it as source nobody
    can read. `.` is the awkward case that proves the rule -- its file is
    `..py`, a dotfile `ls` hides and rglob still finds.
    """
    files = {(p.parent.name, p.stem) for p in (STARTER / 'verbs').rglob('*.py')}
    db = sqlite3.connect(STARTER / 'world.db')
    try:
        orphans = [
            f'#{objnum}:{json.loads(names)[0]}'
            for objnum, names in db.execute('SELECT objnum, names FROM verbs')
            if (str(objnum), json.loads(names)[0]) not in files
        ]
    finally:
        db.close()
    assert not orphans, (
        'these are in world.db with no file on disk, so they are outside git '
        'and unreadable to anyone editing the world: ' + ', '.join(orphans))
