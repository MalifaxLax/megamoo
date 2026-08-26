"""Verb aliases in the shipped starter world.

An alias has no representation on disk.  A verb file is named for one of
its names -- ``look.py`` for ``['look', 'l']``, ``n.py`` for the two dozen
direction names -- and the rest live only on the name list in the
database.  So nothing in a diff, a grep, or a rebuilt-from-disk world will
tell you an alias went missing; it just stops answering.

These read the world.db that ``megamoo init`` copies out, which is the
one a pip user gets.
"""
import json
import sqlite3
from pathlib import Path

import pytest

STARTER = Path(__file__).parent.parent / 'moo' / 'templates' / 'starter' / 'world.db'


def _objects_holding(verb_name):
    """Which objects define a verb by this name, lowest number first.

    The list used to be written out -- (3, 15, 16, 17) -- and #15, #16 and
    #17 stopped being the rooms when the starter adopted sf's numbering, so
    the search found nothing and the test failed claiming `look` was missing
    from a world that has it.  A test for aliases should not also be a
    second, unmaintained copy of the object map.
    """
    with sqlite3.connect(f'file:{STARTER}?mode=ro', uri=True) as db:
        return [objnum for objnum, names in
                db.execute('select objnum, names from verbs order by objnum')
                if verb_name in json.loads(names)]


def _names_of(verb_substring, objnum=3):
    with sqlite3.connect(f'file:{STARTER}?mode=ro', uri=True) as db:
        for names, in db.execute('select names from verbs where objnum=?',
                                 (objnum,)):
            parsed = json.loads(names)
            if any(verb_substring == n for n in parsed):
                return parsed
    return None


def test_make_answers_to_create():
    """@create is what LambdaMOO calls it and what people type first."""
    names = _names_of('@make')

    assert names is not None, '@make is missing from the starter world'
    assert '@create' in names


def test_the_alias_is_on_the_same_verb_not_a_copy():
    """Two verbs would be two bodies to keep in step; one verb, two names."""
    with sqlite3.connect(f'file:{STARTER}?mode=ro', uri=True) as db:
        rows = [json.loads(n) for n, in
                db.execute('select names from verbs where objnum=3')]

    holding = [r for r in rows if '@create' in r or '@make' in r]
    assert len(holding) == 1, f'@make/@create split across {len(holding)} verbs'


@pytest.mark.parametrize('verb,alias', [
    ('look', 'l'),
    ('@make', '@create'),
])
def test_known_aliases_survive(verb, alias):
    """A regression net for the aliases the starter world is expected to have.

    Deliberately small: it exists because an alias cannot be checked by
    looking at the verb tree, so the only place to assert one is a test.
    """
    for objnum in _objects_holding(verb):
        names = _names_of(verb, objnum)
        assert alias in names, f'{verb} on #{objnum} lost its {alias} alias'
        return
    pytest.fail(f'{verb} not found in the starter world')
