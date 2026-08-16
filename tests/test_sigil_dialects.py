"""`&i` and `&u` belong to substitution, not to colour.

One sigil serves two dialects, so the letter after it was the only thing
telling them apart -- and `i`/`u` meant something in both. Substitution
fills a token only when it was handed something to fill it with, so an
`&i` in a message sent without an iobj arrived at the colour pass intact
and was read as reverse video, inverting the rest of the line. The
shipped starter carried a comment in `verbs/23/unlock_.py` explaining why
that verb must not emit `&i` unless it has an iobj: the workaround was
load-bearing, and it only worked while every author remembered.

The transports did not even agree what the letter meant. `moo/color.py`
made `&i` ANSI 7 (reverse); the browser's `_BASIC_CLASSES` made it `.ci`
(italic). The same line rendered two different ways depending on how the
player had connected.

Measured before removing them: across the starter and Shadowfall there
are 2812 colour tokens and 1512 substitution tokens, and of the 171
occurrences of a colliding letter, every one is `&i` used as an indirect
object. Neither world uses `&i` as inverse or `&u` as underline -- there
is no `&u` in either world at all.
"""
from types import SimpleNamespace

import pytest

from moo.color import ColorProcessor
from moo.string_utils import StringUtils
from moo.web.color import moo_colors_to_html


@pytest.fixture
def cp():
    return ColorProcessor(enable_color=True)


@pytest.fixture
def su():
    return StringUtils()


# ---------------------------------------------------------------------------
#   The bug, on both transports
# ---------------------------------------------------------------------------

def test_unfilled_indirect_object_is_not_reverse_video(cp):
    """The reported failure: no iobj, so no substitution, so no colour."""
    out = cp.process('You unlock the door with &i.', 'moo')

    assert '\x1b' not in out
    assert out == 'You unlock the door with &i.'


def test_unfilled_noun_token_is_not_underline(cp):
    """`&u` needs a uob, which is rarer than an iobj -- so it leaked more."""
    out = cp.process('a &u lies here', 'moo')

    assert '\x1b' not in out
    assert out == 'a &u lies here'


def test_the_browser_agrees_with_telnet(cp):
    """
    The two paths disagreed: ANSI 7 here, CSS italic there.

    Neither is right, and a world cannot be authored against a code whose
    meaning depends on the player's client.
    """
    assert '\x1b' not in cp.process('with &i.', 'moo')
    assert 'span' not in moo_colors_to_html('with &i.')


def test_unlock_no_longer_needs_its_workaround(cp, su):
    """
    The sentence `unlock_.py` refused to send, sent.

    It branched to a second message rather than let an unfilled `&i`
    reach the colour pass.  With the letter out of the colour map the
    unfilled token is just text, so the branch is a choice about wording
    rather than a guard against corrupting the screen.
    """
    template = 'You unlock &d with &i.'
    door = SimpleNamespace(name='the door')

    out = cp.process(su.esub(template, dob=door), 'moo')

    assert out == 'You unlock the door with &i.'


# ---------------------------------------------------------------------------
#   Substitution still owns the letters
# ---------------------------------------------------------------------------

def test_a_filled_indirect_object_still_substitutes(su, cp):
    key = SimpleNamespace(name='a brass key')
    door = SimpleNamespace(name='the door')

    text = su.esub('You unlock &d with &i.', dob=door, iob=key)

    assert text == 'You unlock the door with a brass key.'
    assert cp.process(text, 'moo') == 'You unlock the door with a brass key.'


def test_a_substituted_name_containing_the_letter_is_still_safe(su, cp):
    """
    Names are protected through substitution; colour must not undo it.

    An object called `a &i` would otherwise have put reverse video into a
    line that never asked for one -- the same class of bug one layer on.
    """
    odd = SimpleNamespace(name='a &i')

    out = cp.process(su.esub('You see &d.', dob=odd), 'moo')

    assert '\x1b' not in out


# ---------------------------------------------------------------------------
#   Nothing was lost: the attributes are spelled out
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('name,sgr', [
    ('reverse', 7), ('inverse', 7), ('underline', 4),
    ('bold', 1), ('italic', 3), ('blink', 5),
])
def test_named_attributes_on_telnet(cp, name, sgr):
    assert cp.process(f'&<{name}>X', 'moo') == f'\x1b[{sgr}mX'


@pytest.mark.parametrize('name,cls', [
    ('reverse', 'cv'), ('inverse', 'cv'), ('underline', 'cu'),
    ('bold', 'ch'), ('italic', 'ci'), ('blink', 'cf'),
])
def test_named_attributes_in_the_browser(name, cls):
    assert moo_colors_to_html(f'&<{name}>X') == f'<span class="{cls}">X</span>'


def test_named_reset_closes_spans_like_the_letter_does():
    """`&<normal>` is a reset, and a reset closes rather than opens."""
    assert moo_colors_to_html('&r!red&<normal>plain') == \
        '<span class="cr">!red</span>plain'


def test_both_transports_know_the_same_attribute_names():
    """
    The guard against this whole class of bug coming back.

    `&i` meaning reverse on telnet and italic in a browser is what made
    the old single letters unauthorable.  A name the two do not both
    honour is the same defect with a longer spelling, so the vocabularies
    have to stay equal -- which is also why ANSI 2 (dim) is in neither:
    client.css defines no dim rule.
    """
    from moo.color import MOO_ATTR_NAMES
    from moo.web.color import _EXTENDED_CLASSES

    # 'normal'/'reset' are resets, handled in the browser's main loop
    # rather than by an opening span, so they are not in its class map.
    assert set(MOO_ATTR_NAMES) - {'normal', 'reset'} == set(_EXTENDED_CLASSES)


def test_an_unknown_attribute_name_is_left_as_text(cp):
    """Neither transport may invent a rendering for a name it lacks."""
    assert cp.process('&<dim>x', 'moo') == '&<dim>x'
    assert 'span' not in moo_colors_to_html('&<dim>x')


def test_an_attribute_name_is_not_read_as_a_background():
    """The 'bg' prefix is stripped after the name lookup, not before."""
    assert moo_colors_to_html('&<bg21>x') == '<span class="bg21">x</span>'
    assert ColorProcessor(True).process('&<bg21>x', 'moo') == '\x1b[48;5;21mx'


# ---------------------------------------------------------------------------
#   Colour itself is untouched
# ---------------------------------------------------------------------------

def test_ordinary_colour_still_works(cp):
    assert cp.process('&r!red&n', 'moo') == '\x1b[31m!red\x1b[0m'
    assert cp.process('&<245>dim&n', 'moo') == '\x1b[38;5;245mdim\x1b[0m'
    assert cp.process('&h!bold&n', 'moo') == '\x1b[1m!bold\x1b[0m'


def test_a_doubled_sigil_is_still_a_literal_one(cp):
    assert cp.process('100&& done', 'moo') == '100& done'
    assert moo_colors_to_html('100&&') == '100&'


# ---------------------------------------------------------------------------
#   Stripping removes exactly what processing converts
# ---------------------------------------------------------------------------

def test_strip_leaves_what_process_leaves(cp):
    """
    They used to disagree.

    `strip_colors` matched a blanket `&[a-zA-Z]`, so a letter the colour
    map does not know was removed when colour was off and kept when it
    was on -- and the width used for word-wrapping was measured with the
    stripping rule.  An unfilled `&i` vanished on one path and survived
    on the other; so did Shadowfall's verb-local `&l`.
    """
    for text in ('with &i.', 'a &u here', 'wears &d on &l'):
        assert cp.strip_colors(text) == text
        assert '\x1b' not in cp.process(text, 'moo')


def test_strip_still_removes_real_codes(cp):
    assert cp.strip_colors('&r!red&n') == '!red'
    assert cp.strip_colors('&<245>dim&n') == 'dim'
    assert cp.strip_colors('&<reverse>x&n') == 'x'
