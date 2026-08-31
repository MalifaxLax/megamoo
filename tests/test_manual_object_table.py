"""The architecture manual's object table must describe the shipped world.

`01-architecture.md` opens with "Read it first", and its core-hierarchy
table is the reference a builder works from: which object to parent a new
room to, where the player commands live, what `$globals` is. It drifted a
whole band of numbers away from the starter world and nothing noticed,
because nothing here read it -- the table said player commands live on
**#16 (OCRoom)** and **#17 (ICRoom)** while the shipped world had OCRoom
at #12, ICRoom at #13, and #16/#17 holding GoExit and ClosableGoExit.
A builder following it would parent rooms to an exit.

Every other doc check in this suite works the same way: assert the prose
against the artifact rather than trusting a human to re-read both. See
`test_guide_verb_count` and `test_command_reference`.

Only rows naming a single object are checked. The range rows (#24-#26,
#30-#38) are prose and stay prose.
"""
import pathlib
import re
import sqlite3

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
MANUAL = ROOT / 'docs' / 'manual' / '01-architecture.md'
STARTER = ROOT / 'moo' / 'templates' / 'starter' / 'world.db'

# `| #12 | OCRoom | #11 | OOC room; ... |`
ROW = re.compile(r'^\|\s*#(\d+)\s*\|\s*([^|]+?)\s*\|\s*(—|#\d+)\s*\|')


def _table_rows():
    """The single-object rows of the core-hierarchy table, in order."""
    if not MANUAL.is_file():
        pytest.skip('architecture manual not present')
    rows = []
    in_table = False
    for line in MANUAL.read_text(encoding='utf-8').splitlines():
        if line.startswith('| # | Object | Parent | Role |'):
            in_table = True
            continue
        if in_table:
            if not line.startswith('|'):
                break
            m = ROW.match(line)
            if m:
                objnum, noun, parent = m.groups()
                rows.append((int(objnum), noun,
                             None if parent == '—' else int(parent[1:])))
    assert rows, 'the core object hierarchy table was not found or not parsed'
    return rows


@pytest.fixture(scope='module')
def world():
    if not STARTER.is_file():
        pytest.skip('starter world not present')
    db = sqlite3.connect(f'file:{STARTER}?mode=ro', uri=True)
    rows = {n: (noun, parent) for n, noun, parent
            in db.execute('select objnum, noun, parent from objects')}
    db.close()
    return rows


def test_the_table_was_parsed():
    """A regex that quietly matches nothing would pass every test below."""
    rows = _table_rows()
    assert len(rows) >= 20, f'only {len(rows)} rows parsed; the table changed shape'


def test_every_listed_object_exists(world):
    missing = [f'#{n} ({noun})' for n, noun, _ in _table_rows()
               if n not in world]
    assert not missing, f'the manual lists objects the starter world lacks: {missing}'


def test_every_listed_object_has_the_name_the_manual_gives_it(world):
    wrong = [f'#{n}: manual says {noun!r}, world says {world[n][0]!r}'
             for n, noun, _ in _table_rows()
             if n in world and world[n][0] != noun]
    assert not wrong, 'the manual renames objects:\n  ' + '\n  '.join(wrong)


def test_every_listed_parent_is_the_real_parent(world):
    """The half that drifted: a whole band of the tree shifted by four."""
    wrong = [f'#{n} ({noun}): manual says parent #{parent}, '
             f'world says #{world[n][1]}'
             for n, noun, parent in _table_rows()
             if n in world and parent is not None and world[n][1] != parent]
    assert not wrong, 'the manual misparents objects:\n  ' + '\n  '.join(wrong)


def test_the_room_classes_match_globals_room_types(world):
    """`$globals.room_types` is what `@dig` resolves; the table must agree."""
    db = sqlite3.connect(f'file:{STARTER}?mode=ro', uri=True)
    row = db.execute("select value from properties "
                     "where objnum=27 and name='room_types'").fetchone()
    db.close()
    if not row:
        pytest.skip('$globals.room_types not present in the starter world')
    import json
    types = json.loads(row[0])
    listed = {noun: n for n, noun, _ in _table_rows()}
    for key, expected_noun in (('ooc', 'OCRoom'), ('ic', 'ICRoom'),
                               ('room', 'BaseRoom')):
        assert types[key] == listed[expected_noun], (
            f'$globals.room_types[{key!r}] is #{types[key]}, but the manual '
            f'puts {expected_noun} at #{listed[expected_noun]}')
