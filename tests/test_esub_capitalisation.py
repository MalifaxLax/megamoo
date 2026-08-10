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
"""
from types import SimpleNamespace

import pytest

from moo.string_utils import StringUtils, _capitalised


@pytest.fixture
def su():
    return StringUtils()


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
])
def test_capitalised_edge_cases(value, expected):
    assert _capitalised(value) == expected


def test_esub_no_longer_reads_cname():
    """A cname set deliberately must not quietly win again."""
    import inspect
    from moo import string_utils

    body = inspect.getsource(string_utils.StringUtils.esub)
    assert 'cname' not in body
