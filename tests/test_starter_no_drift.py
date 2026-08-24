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

The same rule applies to deciding which verb a *file* is, and it took a
Python upgrade to notice it had been broken here. These tests used to
walk `rglob('*.py')` and read the name off `Path.stem`; the loader walks
`scan_verb_files` and takes `fname[:-3]`. Those agreed on every ordinary
name and disagreed on exactly one: `#15`'s `.`, whose file is `..py`.
Python 3.14 changed `Path('..py').stem` from `'.'` to `'..py'`, so on
3.14 these tests reported the `.` verb as having no file at all while
the server loaded it perfectly well. The test was wrong, not the engine.
So the scan is imported too, and there is now no second opinion about
what a verb file is called.
"""
import json
import pathlib
import sqlite3

import pytest

from moo.server import _verb_matches_file
from moo.verb_loader import scan_verb_files

STARTER = pathlib.Path(__file__).resolve().parent.parent / 'moo' / 'templates' / 'starter'


class _StoredVerb:
    """The shape `_verb_matches_file` reads, built from a database row."""

    def __init__(self, names, code, perms, min_lengths, hidden, parent_type):
        self.names = names
        self.code = code
        self.perms = perms
        self.min_lengths = min_lengths
        self.hidden = hidden
        # Read from the row rather than defaulted.  The double exists to be
        # whatever the shipped database actually holds; a field it invents a
        # value for is a field this test cannot detect drift in, which is the
        # one job it has.
        self.parent_type = parent_type


def _stored_verbs():
    db = sqlite3.connect(STARTER / 'world.db')
    try:
        out = {}
        for objnum, names, code, perms, min_lengths, hidden, parent_type \
                in db.execute(
                'SELECT objnum, names, code, perms, min_lengths, hidden, '
                'parent_type FROM verbs'):
            parsed = json.loads(names)
            verb = _StoredVerb(parsed, code, perms,
                               json.loads(min_lengths or '{}'), bool(hidden),
                               parent_type)
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
    for objnum, name, filepath in scan_verb_files(str(STARTER / 'verbs')):
        verb = stored.get((objnum, name))
        if verb is None:
            drift.append(f'{objnum}/{name}: no such verb in world.db')
            continue
        if not _verb_matches_file(verb, pathlib.Path(filepath).read_text(),
                                  name):
            drift.append(f'{objnum}/{name}')
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
                           code, verb.perms, verb.min_lengths, verb.hidden,
                           verb.parent_type)
    assert not _verb_matches_file(tampered, code, name), (
        'a names-only difference must be caught; code equality is not enough')


@pytest.mark.skipif(not (STARTER / 'world.db').is_file(),
                    reason='starter template not present')
def test_the_check_would_notice_a_type_only_difference():
    """The same guard for `Type:`, because it has already been got wrong.

    When `Type:` was added, seventy-four verb files were rewritten while a
    server that did not know the field was still running.  Its watcher pushed
    the new code, the code then matched, and the restart onto the engine that
    *did* know the field found every verb current and read none of them --
    seventy-four verbs declaring themselves functions on disk while the
    database called them commands, silently.

    Every field a verb file can declare has to be a field this comparison
    knows about, or the next one added repeats it.
    """
    stored = _stored_verbs()
    (objnum, name), verb = next(iter(stored.items()))
    code = verb.code or ''
    assert _verb_matches_file(verb, code, name)

    tampered = _StoredVerb(verb.names, code, verb.perms, verb.min_lengths,
                           verb.hidden, 'moo.verb_types.FunctionVerb')
    assert not _verb_matches_file(tampered, code, name), (
        'a type-only difference must be caught: the file says command and '
        'the database says function, and nothing else differs')


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
        for objnum, name, filepath in scan_verb_files(str(STARTER / 'verbs')):
            row = db.execute(
                'SELECT auth FROM verbs WHERE objnum=? AND names LIKE ?',
                (objnum, f'%"{name}"%')).fetchone()
            if row is None:
                continue
            declared = auth_level_required(pathlib.Path(filepath).read_text())
            if row[0] != declared:
                wrong.append(f'{objnum}/{name}: stored {row[0]}, '
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
    `..py`, a dotfile `ls` hides, and the name it maps to is whatever the
    loader says it is rather than whatever `pathlib` says this year.
    """
    files = {(objnum, name)
             for objnum, name, _ in scan_verb_files(str(STARTER / 'verbs'))}
    db = sqlite3.connect(STARTER / 'world.db')
    try:
        orphans = [
            f'#{objnum}:{json.loads(names)[0]}'
            for objnum, names in db.execute('SELECT objnum, names FROM verbs')
            if (objnum, json.loads(names)[0]) not in files
        ]
    finally:
        db.close()
    assert not orphans, (
        'these are in world.db with no file on disk, so they are outside git '
        'and unreadable to anyone editing the world: ' + ', '.join(orphans))
