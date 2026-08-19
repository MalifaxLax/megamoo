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
    """Neither transport may invent a rendering for a name it lacks.

    The example here used to be `dim`, chosen because no such name
    existed.  One does now -- as a *colour*, an alias for 245, not as the
    ANSI 2 attribute this file is otherwise about -- so this check needs a
    name that is still genuinely absent.  See the two tests below.
    """
    assert cp.process('&<mauve>x', 'moo') == '&<mauve>x'
    assert 'span' not in moo_colors_to_html('&<mauve>x')


@pytest.mark.parametrize('named, numeric', [
    ('&<dim>x&n',   '&<245>x&n'),
    ('&<DIM>x&n',   '&<245>x&n'),      # names are case-insensitive
    ('&<bgdim>x&n', '&<bg245>x&n'),    # and the bg prefix composes
])
def test_a_named_colour_renders_as_its_number(cp, named, numeric):
    """`&<dim>` is an alias, so it may not render as a thing of its own.

    Both transports resolve the name to its index and then take the
    ordinary xterm-256 path, which is what stops the two spellings
    drifting the way `&i` did.
    """
    assert cp.process(named, 'moo') == cp.process(numeric, 'moo')
    assert moo_colors_to_html(named) == moo_colors_to_html(numeric)


def test_dim_is_a_colour_and_not_the_ansi_attribute():
    """ANSI 2 is still absent, and still deliberately.

    client.css defines no rule for it and a fair share of terminals draw
    it as ordinary text, so this name means one specific grey rather than
    "whatever colour you were using, fainter".  Anything that later wants
    the composable attribute has to add the CSS first.
    """
    from moo.color import MOO_ATTR_NAMES, MOO_COLOR_NAMES

    assert MOO_COLOR_NAMES['dim'] == 245
    assert 'dim' not in MOO_ATTR_NAMES


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
