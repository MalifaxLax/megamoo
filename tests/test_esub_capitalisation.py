"""&S and friends capitalise `name` rather than reading a `cname` property.

cname was a second copy of the same fact, and a second copy drifts. An
object that never set one inherited its *prototype's*, so a character
with a perfectly good name of her own was announced to the room as
"ICharacter walks in from the west." Six characters in Shadowfall were
in that state, and the failure is invisible until somebody walks through
a door.

Measured before removing it: of 123 cname values in the starter world, 0
differed from capitalising name; of 405 in Shadowfall, 3 differed and all
three were *un*capitalised -- wrong rather than deliberate. The property
was redundant wherever it was right.

`su` was `moo.string_utils`.  It is $string_utils in the world now, so it
arrives as a fixture from `conftest.py` -- a proxy whose attribute access is
a verb call.  The bodies below are unchanged: what was true of the module has
to stay true of the verb, and rewriting the assertions at the same time as
the code would have stopped them being evidence.
"""
from types import SimpleNamespace

import pytest



def test_a_stale_inherited_cname_is_ignored(su):
    """The reported bug, in one line."""
    sinda = SimpleNamespace(name='Sinda', cname='ICharacter')

    assert su.esub('&S walks in.', sub=sinda) == 'Sinda walks in.'


def test_no_cname_is_not_a_problem(su):
    """Nothing has to be backfilled for an emit to read correctly."""
    assert su.esub('&S walks in.', sub=SimpleNamespace(name='Sinda')) == 'Sinda walks in.'


def test_an_article_is_raised(su):
    o = SimpleNamespace(name='a training dummy')

    assert su.esub('&S blocks the way.', sub=o) == 'A training dummy blocks the way.'


def test_only_the_first_letter_changes(su):
    """Title-casing would wreck both a proper noun and an article phrase."""
    assert su.esub('&S.', sub=SimpleNamespace(name='Malifax Lax')) == 'Malifax Lax.'
    assert su.esub('&S.', sub=SimpleNamespace(name='an old rusty sword')) == 'An old rusty sword.'


def test_the_lowercase_tokens_are_untouched(su):
    o = SimpleNamespace(name='an old rusty sword')

    assert su.esub('You take &d.', dob=o) == 'You take an old rusty sword.'
    assert su.esub('You see &s.', sub=SimpleNamespace(name='Sinda')) == 'You see Sinda.'


@pytest.mark.parametrize('value,expected', [
    ('', ''), (None, None), ('x', 'X'), ('Sinda', 'Sinda'),
    ('a hat', 'A hat'), ('7 swords', '7 swords'),
    # The cases str.capitalize() gets wrong, which is why it is not used.
    ('an OLD sword', 'An OLD sword'), ('MacLeod', 'MacLeod'),
    ("O'Brien", "O'Brien"), ('Mary-Jane', 'Mary-Jane'),
])
def test_capitalise_edge_cases(su, value, expected):
    assert su.capitalise(value) == expected


def test_there_is_exactly_one_capitalise(_utils_world):
    """
    The rule lived in three places -- su.capitalise, a module-level
    _capitalised, and a capitalize_first builtin nothing called. Three
    copies of a rule are two chances for it to drift.

    Two of the three are gone with `moo/string_utils.py`; the assertion that
    survives is about the modules that are still here.  $string_utils holds
    the only `capitalise` now, so the count is asked of the world.
    """
    from moo import builtins, utils
    from moo.object_utils import system_ref

    assert not hasattr(utils, 'capitalize_first')
    assert not hasattr(builtins, 'capitalize_first')

    db, _ = _utils_world
    holders = [o.objnum for o in db.objects()
               for v in o.verbs if 'capitalise' in v.names]
    assert holders == [system_ref(db, 'string_utils').objnum], holders


def test_esub_no_longer_reads_cname(_utils_world):
    """A cname set deliberately must not quietly win again.

    Read off the verb rather than off `inspect.getsource` of a class that no
    longer exists.  The verb's code is a column in the database, which is
    the same question asked of the thing that now answers it.
    """
    from moo.object_utils import system_ref

    db, _ = _utils_world
    su_obj = system_ref(db, 'string_utils')
    esub = [v for v in su_obj.verbs if 'esub' in v.names]
    assert len(esub) == 1, 'expected one esub on $string_utils, got %d' % len(esub)
    assert 'cname' not in (esub[0].code or '')
