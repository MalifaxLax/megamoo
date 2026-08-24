"""Reading and writing a verb's metadata in its own docstring.

The round trip is the point: whatever the database holds must survive
being written to a file and read back, or a world rebuilt from its verb
tree comes back subtly different from the one that was dumped.
"""
import pytest

from moo.verb_meta import parse_verb_meta, render_verb_meta


def _file(body):
    return '"""\n%s"""\nreturn 1\n' % body


# ------------------------------------------------------------------
# Reading
# ------------------------------------------------------------------

def test_a_plain_verb_file_declares_an_ordinary_verb():
    """The common case: no metadata means no aliases, visible, rx, command."""
    meta = parse_verb_meta(_file('Does a thing.\n'), 'look')

    assert meta == {'names': ['look'], 'min_lengths': {},
                    'hidden': False, 'perms': 'rx',
                    'parent_type': 'moo.verb_types.MasterVerb'}


# ------------------------------------------------------------------
# Type
# ------------------------------------------------------------------

def test_type_function_names_the_verb_type():
    meta = parse_verb_meta(_file('Type: function\n'), 'capitalise')
    assert meta['parent_type'] == 'moo.verb_types.FunctionVerb'


def test_type_accepts_a_dotted_path_for_a_world_s_own_type():
    """A world with a custom verb type must be able to name it without this
    module having heard of it."""
    meta = parse_verb_meta(_file('Type: mygame.verbs.SpellVerb\n'), 'cast')
    assert meta['parent_type'] == 'mygame.verbs.SpellVerb'


def test_command_is_the_default_and_is_never_written():
    """A line saying the default is a line that will be copied around and
    eventually be wrong.  Omitting it keeps one spelling of ordinary."""
    code = _file('Does a thing.\n')
    out = render_verb_meta(code, ['look'])
    assert 'Type:' not in out
    out = render_verb_meta(code, ['look'],
                           parent_type='moo.verb_types.MasterVerb')
    assert 'Type:' not in out


def test_type_round_trips_through_render_and_parse():
    code = _file('Capitalises a word.\n')
    out = render_verb_meta(code, ['capitalise'], hidden=True,
                           parent_type='moo.verb_types.FunctionVerb')
    assert 'Type:    function' in out
    back = parse_verb_meta(out, 'capitalise')
    assert back['parent_type'] == 'moo.verb_types.FunctionVerb'
    assert back['hidden'] is True


def test_rendering_a_type_back_to_default_removes_the_line():
    """Same rule as Hidden: un-declaring takes the line out rather than
    leaving a `Type: command` behind to be misread later as deliberate."""
    code = render_verb_meta(_file('x.\n'), ['x'],
                            parent_type='moo.verb_types.FunctionVerb')
    assert 'Type:' in code
    code = render_verb_meta(code, ['x'])
    assert 'Type:' not in code


def test_aliases_follow_the_primary_name():
    meta = parse_verb_meta(_file('Aliases: @create, @build\n'), '@make')

    assert meta['names'] == ['@make', '@create', '@build']


def test_the_primary_is_never_duplicated():
    """A file that lists its own name is not punished for it."""
    meta = parse_verb_meta(_file('Aliases: @make, @create\n'), '@make')

    assert meta['names'] == ['@make', '@create']


def test_abbreviations_read_as_a_table():
    meta = parse_verb_meta(_file('Aliases: l\nAbbrev: look=1, l=1\n'), 'look')

    assert meta['min_lengths'] == {'look': 1, 'l': 1}


def test_adverb_spelling_is_accepted_in_aliases():
    """`@adverb` has always taken name(min); a name copied from it parses."""
    meta = parse_verb_meta(_file('Aliases: l(1), x(2)\n'), 'look')

    assert meta['names'] == ['look', 'l', 'x']
    assert meta['min_lengths'] == {'l': 1, 'x': 2}


def test_an_abbreviation_for_an_unknown_name_is_dropped():
    """Otherwise it travels between files by copy-paste forever."""
    meta = parse_verb_meta(_file('Abbrev: look=1, nosuch=2\n'), 'look')

    assert meta['min_lengths'] == {'look': 1}


@pytest.mark.parametrize('value,expected', [
    ('yes', True), ('Yes', True), ('true', True), ('1', True), ('on', True),
    ('no', False), ('false', False), ('0', False),
])
def test_hidden_accepts_the_obvious_spellings(value, expected):
    assert parse_verb_meta(_file('Hidden: %s\n' % value), 'v')['hidden'] is expected


def test_perms_default_to_rx():
    assert parse_verb_meta(_file('x\n'), 'v')['perms'] == 'rx'
    assert parse_verb_meta(_file('Perms: rxd\n'), 'v')['perms'] == 'rxd'


def test_only_the_docstring_is_searched():
    """A body that prints "Hidden: yes" does not thereby hide the verb.

    This is the reason the region is bounded rather than the file being
    scanned line by line -- help tables and status messages are exactly
    the kind of text that would trip a looser match.
    """
    code = ('"""\nA status report.\n"""\n'
            'pobj.msg("Hidden: yes")\n'
            'pobj.msg("Aliases: nope")\n')
    meta = parse_verb_meta(code, 'status')

    assert meta['hidden'] is False
    assert meta['names'] == ['status']


def test_a_file_with_no_docstring_reads_as_defaults():
    meta = parse_verb_meta('return 1\n', 'v')

    assert meta['names'] == ['v'] and meta['hidden'] is False


# ------------------------------------------------------------------
# Writing
# ------------------------------------------------------------------

def test_nothing_to_declare_writes_nothing():
    """The great majority of verb files must gain no noise at all."""
    original = _file('Does a thing.\n')

    assert render_verb_meta(original, ['look']) == original


def test_round_trip():
    original = _file('Does a thing.\n\nAuth: gm3+ (auth_level 3)\n')
    written = render_verb_meta(
        original, ['@make', '@create'], {'@make': 3}, hidden=True, perms='rxd')
    back = parse_verb_meta(written, '@make')

    assert back['names'] == ['@make', '@create']
    assert back['min_lengths'] == {'@make': 3}
    assert back['hidden'] is True
    assert back['perms'] == 'rxd'


def test_metadata_sits_above_the_auth_line():
    written = render_verb_meta(
        _file('Does a thing.\n\nAuth: gm3+ (auth_level 3)\n'),
        ['@make', '@create'])

    body = written.split('"""')[1]
    assert body.index('Aliases:') < body.index('Auth:')


def test_rendering_twice_does_not_accumulate():
    once = render_verb_meta(_file('x\n'), ['a', 'b'], {'a': 1}, hidden=True)
    twice = render_verb_meta(once, ['a', 'b'], {'a': 1}, hidden=True)

    assert once == twice
    assert once.count('Aliases:') == 1


def test_clearing_removes_the_line_rather_than_negating_it():
    """`Hidden: no` left behind would later read as deliberate."""
    hidden = render_verb_meta(_file('x\n'), ['a'], hidden=True)
    assert 'Hidden' in hidden

    shown = render_verb_meta(hidden, ['a'], hidden=False)
    assert 'Hidden' not in shown
    assert parse_verb_meta(shown, 'a')['hidden'] is False


def test_removing_an_alias_removes_it_from_the_file():
    two = render_verb_meta(_file('x\n'), ['a', 'b'])
    one = render_verb_meta(two, ['a'])

    assert parse_verb_meta(one, 'a')['names'] == ['a']
    assert 'Aliases' not in one


def test_a_file_without_a_docstring_is_left_alone():
    """Inventing a docstring would mean inventing a summary line."""
    code = 'return 1\n'

    assert render_verb_meta(code, ['a', 'b']) == code


def test_the_body_is_never_touched():
    code = '"""\nDoc.\n"""\nx = 1\nreturn x\n'
    written = render_verb_meta(code, ['a', 'b'])

    assert written.endswith('"""\nx = 1\nreturn x\n')
