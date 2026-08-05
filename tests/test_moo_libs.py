"""
Tests for the ported LambdaMOO utility objects.

Every expectation here comes from the original MOO definitions -- JHCore's
and LambdaCore's, which agree on the contracts even where their
implementations differ.  The indices are 1-based on purpose: @port shifts
subscripts but not call arguments, so a shim counting from zero would put
every ported call off by one.
"""

import pytest

from moo.moo_libs import cdu, cu, lu


# --------------------------------------------------------------------------
# $list_utils -- 1-based, per the originals
# --------------------------------------------------------------------------

def test_assoc_returns_the_matching_element():
    # "returns the first element of `list' whose own index-th element is
    # target.  Index defaults to 1."
    assert lu.assoc('y', [['z', 1], ['y', 2], ['x', 5]]) == ['y', 2]


def test_assoc_returns_empty_when_absent():
    # "returns {} if no such element is found"
    assert lu.assoc('q', [['z', 1]]) == []


def test_assoc_index_is_one_based():
    assert lu.assoc(2, [['z', 1], ['y', 2]], 2) == ['y', 2]


def test_assoc_skips_elements_too_short():
    # LambdaCore guards this with `t[indx] ! E_RANGE => 0'
    assert lu.assoc('x', [['a'], ['x', 1]], 2) == []


def test_iassoc_is_a_one_based_position():
    assert lu.iassoc('y', [['z', 1], ['y', 2]]) == 2


def test_iassoc_returns_zero_when_absent():
    # Zero, not -1: ported code tests it for truth.
    assert lu.iassoc('q', [['z', 1]]) == 0


def test_slice_takes_the_nth_of_each():
    # JHCore: slice({{"z",1},{"y",2},{"x",5}},2) => {1,2,5}
    assert lu.slice([['z', 1], ['y', 2], ['x', 5]], 2) == [1, 2, 5]


def test_slice_defaults_to_the_first():
    assert lu.slice([['z', 1], ['y', 2]]) == ['z', 'y']


def test_slice_with_a_list_index_reorders():
    # JHCore: slice({{"z",1,3},{"y",2,4}},{2,1}) => {{1,"z"},{2,"y"}}
    assert lu.slice([['z', 1, 3], ['y', 2, 4]], [2, 1]) == [[1, 'z'], [2, 'y']]


def test_remove_duplicates_keeps_first_order():
    assert lu.remove_duplicates([3, 1, 3, 2, 1]) == [3, 1, 2]


def test_setadd_only_adds_when_absent():
    assert lu.setadd([1, 2], 2) == [1, 2]
    assert lu.setadd([1, 2], 3) == [1, 2, 3]


def test_setremove_removes_one():
    assert lu.setremove([1, 2, 2], 2) == [1, 2]


def test_find_insert_is_one_based():
    assert lu.find_insert([1, 3, 5], 4) == 3
    assert lu.find_insert([1, 3, 5], 9) == 4


def test_make_repeats_a_value():
    assert lu.make(3, 'x') == ['x', 'x', 'x']
    assert lu.make(0) == []


def test_sort_with_parallel_keys():
    assert lu.sort(['c', 'a', 'b'], [3, 1, 2]) == ['a', 'b', 'c']


# --------------------------------------------------------------------------
# $code_utils
# --------------------------------------------------------------------------

def test_parse_verbref_splits_object_and_verb():
    assert cdu.parse_verbref('#3:look') == ['#3', 'look']


def test_parse_verbref_returns_empty_without_a_colon():
    assert cdu.parse_verbref('nothing') == []


def test_parse_propref_splits_object_and_property():
    assert cdu.parse_propref('#3.name') == ['#3', 'name']


def test_tonum_is_zero_for_nonsense():
    assert cdu.tonum('12') == 12
    assert cdu.tonum('banana') == 0


def test_prepositions_round_trip():
    assert cdu.short_prep('at/to') == 'at'
    assert cdu.full_prep('to') == 'at/to'
    assert cdu.full_prep('with') == 'with/using'


# --------------------------------------------------------------------------
# $command_utils
# --------------------------------------------------------------------------

class _Spy:
    def __init__(self):
        self.said = []

    def msg(self, text, **kw):
        self.said.append(text)


def test_object_match_failed_reports_and_returns_true():
    who = _Spy()
    assert cu.object_match_failed(-1, 'sword', who) is True
    assert 'sword' in who.said[0]


def test_object_match_failed_is_false_on_a_real_match():
    who = _Spy()
    assert cu.object_match_failed(object(), 'sword', who) is False
    assert who.said == []


def test_ambiguous_match_says_so():
    who = _Spy()
    cu.object_match_failed(-2, 'door', who)
    assert 'which' in who.said[0]


def test_yes_or_no_refuses_rather_than_pretending():
    # It blocks for input in MOO; a verb cannot block without stopping the
    # world, so this must not quietly return a guess.
    with pytest.raises(NotImplementedError):
        cu.yes_or_no('really?')


# --------------------------------------------------------------------------
# $code_utils -- the parsing half
#
# Written from LambdaCore's definitions.  The half that resists is not the
# 54-method count but the fact that most of the rest is written in terms of
# server builtins (verb_info, callers, set_task_perms) that this engine does
# not have; mooR supplies those and then runs $code_utils unchanged.
# --------------------------------------------------------------------------

def test_get_prep_finds_the_longest_phrase():
    # LambdaCore: get_prep("in","front","of",...) => {"in front of",...}
    assert cdu.get_prep('in', 'front', 'of', 'box') == ['in front of', 'box']


def test_get_prep_matches_a_single_word():
    assert cdu.get_prep('inside', 'box')[0] == 'in/inside/into'


def test_get_prep_returns_empty_when_not_a_preposition():
    # LambdaCore: get_prep("frabulous",...) => {"", "frabulous",...}
    assert cdu.get_prep('frabulous', 'x') == ['', 'frabulous', 'x']


def test_parse_argspec_full_form():
    # LambdaCore: {{"this","in front of","any"},{"foo"}}
    assert cdu.parse_argspec('this', 'in', 'front', 'of', 'any', 'foo') == \
        [['this', 'in front of', 'any'], ['foo']]


def test_parse_argspec_bare_specifier():
    assert cdu.parse_argspec('any') == [['any', 'none', 'none'], []]


def test_parse_argspec_reports_a_bad_specifier():
    # The original returns a string rather than a list on failure.
    assert isinstance(cdu.parse_argspec('wibble'), str)


def test_substitute_respects_word_boundaries():
    # "avoiding substitution inside words"
    assert cdu.substitute('cat cathode', [['cat', 'dog']]) == 'dog cathode'


def test_substitute_of_punctuation_is_not_delimited():
    assert cdu.substitute('a%b', [['%', '-']]) == 'a-b'


def test_find_verb_named_is_one_based_and_zero_when_absent():
    class _V:
        def __init__(self, names, perms='rx'):
            self.names, self.perms = names, perms
            self.code = ''

    class _O:
        verbs = [_V(['look']), _V(['get'])]

    assert cdu.find_verb_named(_O(), 'get') == 2
    assert cdu.find_verb_named(_O(), 'nope') == 0


def test_verb_documentation_reads_the_docstring():
    class _V:
        names = ['look']
        perms = 'rx'
        code = '"""Look at a thing.\n\nUsage: look <thing>\n"""\nreturn 1\n'

    class _O:
        verbs = [_V()]

    doc = cdu.verb_documentation(_O(), 'look')
    assert doc[0] == 'Look at a thing.'
    assert cdu.verb_usage(_O(), 'look') == 'look <thing>'
