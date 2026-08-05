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


# --------------------------------------------------------------------------
# The verb-introspection builtins
#
# These are the engine half of $code_utils.  mooR supplies them (bf_verbs,
# bf_callers) and then runs the object unchanged; without them the ported
# half had nothing to call.
# --------------------------------------------------------------------------

class _FakeVerb:
    def __init__(self, names, owner=7, perms='rx', code='x = 1\n'):
        self.names, self.owner, self.perms, self.code = names, owner, perms, code
        self.compiled_code = None


class _FakeObj:
    objnum = 42
    owner = 3

    def __init__(self):
        self.verbs = [_FakeVerb(['look', 'l']), _FakeVerb(['get'])]


def test_verb_info_by_name():
    from moo.builtins import verb_info
    assert verb_info(_FakeObj(), 'look') == [7, 'rx', 'look l']


def test_verb_info_by_one_based_index():
    from moo.builtins import verb_info
    assert verb_info(_FakeObj(), 2)[2] == 'get'


def test_verb_info_missing_returns_the_moo_error():
    from moo.builtins import verb_info
    from moo.moo_compat import E_VERBNF
    assert verb_info(_FakeObj(), 'nope') == E_VERBNF


def test_verb_code_returns_lines():
    from moo.builtins import verb_code
    assert verb_code(_FakeObj(), 'look') == ['x = 1']


def test_frames_unwind():
    from moo.builtins import push_frame, pop_frame, callers
    before = len(callers())
    push_frame(_FakeObj(), 'outer', None, None, owner=3)
    push_frame(_FakeObj(), 'inner', None, None, owner=3)
    # callers() drops your own frame, so from `inner` you see `outer`
    assert [f[1] for f in callers()] == ['outer']
    pop_frame()
    pop_frame()
    assert len(callers()) == before


def test_caller_perms_skips_your_own_frame():
    # Returning yourself would make `caller_perms().wizard` test the wrong
    # object, and that idiom guards real permission checks.
    from moo.builtins import push_frame, pop_frame, callers
    push_frame(_FakeObj(), 'only', None, None, owner=3)
    assert callers() == []      # nothing called us
    pop_frame()


def test_set_task_perms_is_accepted_and_does_nothing():
    # Ported utility verbs open with it out of habit; raising would stop
    # code that is otherwise correct.
    from moo.builtins import set_task_perms
    assert set_task_perms(None) is None


# --------------------------------------------------------------------------
# $perm_utils, the match sentinels, and MOO's regexes
# --------------------------------------------------------------------------

def test_apply_edits_permission_strings():
    from moo.moo_libs import pu
    assert pu.apply('rw', '+x') == 'rwx'
    assert pu.apply('rwx', '-w') == 'rx'
    assert pu.apply('rw', '+x-r') == 'wx'


def test_apply_without_a_sign_replaces():
    from moo.moo_libs import pu
    assert pu.apply('rw', 'rx') == 'rx'


def test_apply_is_idempotent():
    from moo.moo_libs import pu
    assert pu.apply('rw', '+r') == 'rw'


def test_moo_parens_are_literal():
    # The whole reason MOO patterns cannot go straight to `re`: this must
    # match the bracket characters, not capture foo.
    from moo.moo_libs import moo_regex_to_python, moo_match
    assert moo_regex_to_python('(foo)') == r'\(foo\)'
    assert moo_match('a (foo) b', '(foo)')[:2] == [3, 7]
    assert moo_match('a foo b', '(foo)') == []


def test_percent_paren_is_a_group():
    from moo.moo_libs import moo_regex_to_python
    assert moo_regex_to_python('%(foo%)') == '(foo)'


def test_match_offsets_are_one_based_and_inclusive():
    from moo.moo_libs import moo_match
    assert moo_match('abcdef', 'cd')[:2] == [3, 4]


def test_match_folds_case_by_default():
    # Opposite of Python's default, and quietly wrong if not handled.
    from moo.moo_libs import moo_match
    assert moo_match('HELLO', 'hello') != []
    assert moo_match('HELLO', 'hello', 1) == []


def test_match_reports_nine_slots():
    from moo.moo_libs import moo_match
    reps = moo_match('hello', '%(h%)%(e%)')[2]
    assert len(reps) == 9
    assert reps[0] == [1, 1] and reps[2] == [0, -1]


def test_rmatch_takes_the_last_one():
    from moo.moo_libs import moo_match, moo_rmatch
    assert moo_match('a1 a2 a3', 'a[0-9]')[0] == 1
    assert moo_rmatch('a1 a2 a3', 'a[0-9]')[0] == 7


def test_substitute_fills_from_a_match():
    from moo.moo_libs import moo_match, moo_substitute
    m = moo_match('hello world', '%(w%w+%)')
    assert moo_substitute('got %1!', m) == 'got world!'
    assert moo_substitute('[%0]', m) == '[world]'


def test_substitute_of_a_failed_match_changes_nothing():
    from moo.moo_libs import moo_substitute
    assert moo_substitute('got %1', []) == 'got %1'


def test_a_bad_pattern_does_not_raise():
    from moo.moo_libs import moo_match
    assert moo_match('abc', '%(unclosed') == []


def test_the_two_match_failures_stay_distinct():
    # Conflating them would make the "which one did you mean?" branch fire
    # on a plain miss.  Both are falsy, and neither equals the other.
    from moo.moo_libs import FAILED_MATCH, AMBIGUOUS_MATCH
    assert FAILED_MATCH != AMBIGUOUS_MATCH
    assert not FAILED_MATCH and not AMBIGUOUS_MATCH
    assert FAILED_MATCH == FAILED_MATCH


def test_none_never_equals_a_match_sentinel():
    # None is what this engine's matcher really returns, and ported code
    # tests it against these.  The test must be answerable, not a crash.
    from moo.moo_libs import FAILED_MATCH
    assert (None == FAILED_MATCH) is False


def test_port_translates_match_rather_than_marking_it():
    from moo.moo_port import port
    r = port('r = match(argstr, "^%(foo%)$");')
    assert 'moo_match' in r.code and 'match(' in r.code
    assert r.marks == 0


def test_port_supplies_the_import_time_needs():
    from moo.moo_port import port
    r = port('x = time(); y = ctime(x);')
    assert r.code.startswith('import time')
    assert r.marks == 0


def test_port_maps_the_nothing_constants():
    from moo.moo_port import port
    r = port('if (dobj == $nothing || dobj == $failed_match) return; endif')
    assert 'None' in r.code and 'FAILED_MATCH' in r.code
    assert r.marks == 0


def test_setitem_does_not_shift_an_already_shifted_index():
    # @port shifts subscripts as it translates, so MOO's x[1] arrives as
    # x[0].  Shifting again would write to x[-1] -- no error, just the
    # wrong end of the list.
    from moo.moo_builtins import moo_setitem
    lst = [1, 2, 3]
    assert moo_setitem(lst, 0, 9) == [9, 2, 3]


def test_setitem_returns_the_container_not_the_value():
    # MOO's indexed assignment evaluates to the whole list.
    from moo.moo_builtins import moo_setitem
    assert moo_setitem([1, 2], 0, 9) == [9, 2]


def test_setprop_returns_the_value_unlike_setitem():
    from moo.moo_builtins import moo_setprop

    class O:
        pass
    o = O()
    assert moo_setprop(o, 'x', 7) == 7 and o.x == 7


def test_moo_random_includes_both_ends():
    from moo.moo_builtins import random
    seen = {random(3) for _ in range(300)}
    assert seen == {1, 2, 3}


def test_typeof_returns_moos_constants():
    from moo.moo_builtins import typeof, LIST, STR, INT, FLOAT
    assert typeof([1]) == LIST and typeof('a') == STR
    assert typeof(1) == INT and typeof(1.0) == FLOAT


def test_both_type_constant_spellings_agree():
    # JHCore writes LIST, LambdaCore writes TYPE_LIST, and a core that
    # compared one against the other must still get the right answer.
    from moo.moo_builtins import LIST, TYPE_LIST, STR, TYPE_STR
    assert LIST == TYPE_LIST and STR == TYPE_STR


def test_strcmp_is_case_sensitive():
    from moo.moo_builtins import strcmp
    assert strcmp('A', 'a') != 0
    assert strcmp('a', 'a') == 0


def test_moo_raise_raises():
    import pytest
    from moo.moo_builtins import moo_raise
    from moo.properties import MOOError
    with pytest.raises(MOOError):
        moo_raise('E_PERM')


def test_catch_uses_the_fallback_for_a_missing_property():
    # A missing property returns the falsy sentinel rather than raising,
    # so `x.foo ! E_PROPNF => 0' would otherwise sail past the except.
    from moo.builtins import catch
    from moo.objects import _null_attr
    assert catch(lambda: _null_attr, ('E_PROPNF',), lambda: 'd') == 'd'


def test_catch_keeps_a_property_that_really_holds_a_falsy_value():
    # The test is against the sentinel, not against falsiness: a property
    # holding 0 must keep its own value.
    from moo.builtins import catch
    assert catch(lambda: 0, ('E_PROPNF',), lambda: 'd') == 0
    assert catch(lambda: '', ('E_PROPNF',), lambda: 'd') == ''
