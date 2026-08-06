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


def _undefined_variable():
    # LambdaCore #69:E_VARNF, verbatim: the error generator raises each
    # error on purpose, and a bare unbound name is how it makes this one.
    return a                                            # noqa: F821


def test_catch_reads_a_python_nameerror_as_e_varnf():
    from moo.builtins import catch
    assert catch(_undefined_variable, ('E_VARNF',), lambda: 'ok') == 'ok'


def test_catch_reads_the_other_native_failures_as_their_moo_codes():
    from moo.builtins import catch
    assert catch(lambda: [][0], ('E_RANGE',), lambda: 'ok') == 'ok'
    assert catch(lambda: 1 // 0, ('E_DIV',), lambda: 'ok') == 'ok'
    assert catch(lambda: 1 + 'x', ('E_TYPE',), lambda: 'ok') == 'ok'


def test_a_native_failure_with_no_clause_yields_the_error_value():
    # MOO's backtick without `=>` evaluates to the error itself, and
    # MOOError compares by code, which is what ported code goes on to test.
    from moo.builtins import catch
    from moo.properties import MOOError
    assert catch(_undefined_variable) == MOOError('E_VARNF')


def test_a_native_failure_the_clause_does_not_name_still_propagates():
    from moo.builtins import catch
    with pytest.raises(NameError):
        catch(_undefined_variable, ('E_RANGE',), lambda: 'ok')


def test_an_engine_failure_is_not_disguised_as_a_moo_error():
    # Propagating is the point: a bug in the engine is not an error the
    # verb was expecting, and giving it a MOO code would hide it inside
    # somebody's `! ANY'.
    from moo.builtins import catch
    def boom():
        raise SystemError('engine bug')
    with pytest.raises(SystemError):
        catch(boom, ('ANY',), lambda: 'ok')


def test_renumber_returns_the_object_it_was_given():
    # This engine's allocator takes the lowest free number on every create
    # and reuses recycled ones, so an object is already renumbered by the
    # time a verb asks.  LambdaMOO's own renumber rewrites no references
    # either, which is why its manual limits the call to a new object.
    from moo.moo_builtins import renumber, reset_max_object

    class Obj:
        objnum = 7
    o = Obj()
    assert renumber(o) is o
    assert reset_max_object() is None


def test_renumber_refuses_a_non_object():
    from moo.moo_builtins import renumber
    from moo.properties import MOOError
    with pytest.raises(MOOError):
        renumber('not an object')


def test_eval_sees_the_same_moo_builtins_a_verb_does():
    # `/` eval is assembled by a different function from the one that
    # assembles a verb namespace, so the two can drift.  They had: the
    # eval side saw one of moo_builtins' hundred names, which made it
    # useless for poking at freshly imported verbs, since ported code is
    # written entirely in terms of that layer.
    from moo.builtins import _build_eval_globals
    from moo import moo_builtins as mb
    ns = _build_eval_globals({})
    assert [n for n in mb.__all__ if n not in ns] == []


def test_eval_resolves_a_clashing_name_the_way_a_verb_does():
    # Where both modules define a name, moo_builtins wins in a verb, so it
    # must win here too.  `random` is the one that bites: moo_builtins has
    # MOO's random(n), returning 1..n inclusive, while moo.builtins has the
    # Python *module* of that name -- which is not even callable, so
    # `/random(6)` failed while random(6) in a verb worked.
    from moo.builtins import _build_eval_globals
    from moo import moo_builtins as mb
    ns = _build_eval_globals({})
    for name in ('random', 'property_info'):
        assert ns[name] is getattr(mb, name)
    assert sorted({ns['random'](6) for _ in range(200)}) == [1, 2, 3, 4, 5, 6]


def test_moo_splice_inserts_deletes_and_replaces():
    # MOO uses range assignment for all three, naming an empty range to
    # insert -- LambdaCore's @display does `perms[1..0] = " "`.
    from moo.moo_builtins import moo_splice
    assert moo_splice(['a', 'b', 'c'], 0, 1, []) == ['b', 'c']
    assert moo_splice([1, 2, 3], 1, 2, [9, 9]) == [1, 9, 9, 3]
    assert moo_splice('rw', 0, 0, ' ') == ' rw'
    assert moo_splice('ab', 2, 2, 'c') == 'abc'


def test_moo_splice_leaves_the_original_alone():
    # MOO lists are values: the assignment builds a new one and rebinds.
    from moo.moo_builtins import moo_splice
    original = ['a', 'b']
    moo_splice(original, 0, 1, ['x'])
    assert original == ['a', 'b']


def test_moo_splice_refuses_a_mismatched_type():
    from moo.moo_builtins import moo_splice
    from moo.properties import MOOError
    with pytest.raises(MOOError):
        moo_splice([1], 0, 1, 'x')
    with pytest.raises(MOOError):
        moo_splice('ab', 0, 1, ['x'])


def test_atan_two_argument_form_keeps_the_quadrant():
    # atan(y, x) is C's atan2; atan(y / x) loses which quadrant it was in.
    import math
    from moo.moo_builtins import atan
    assert round(atan(1, -1), 6) == round(math.pi * 3 / 4, 6)
    assert round(atan(1), 6) == round(math.pi / 4, 6)


def test_ceil_and_trunc_return_floats_like_moos():
    from moo.moo_builtins import ceil, trunc
    assert ceil(1.2) == 2.0 and isinstance(ceil(1.2), float)
    assert trunc(-1.8) == -1.0


def test_floatstr_honours_precision():
    from moo.moo_builtins import floatstr
    assert floatstr(3.14159, 2) == '3.14'
    assert floatstr(3.0, 0) == '3'
    assert 'e' in floatstr(1234.5, 2, True)


def test_value_bytes_recurses_into_containers():
    # A big list must not report the size of a pointer.
    from moo.moo_builtins import value_bytes
    assert value_bytes([1, 2, 3, 4]) > value_bytes([1])


def test_force_input_does_nothing():
    # It would let ported code issue commands as another player, under
    # their permissions, without their knowledge.
    from moo.moo_builtins import force_input
    assert force_input(None, 'quit') is None


# --------------------------------------------------------------------------
# Operators that look identical in both languages and are not.
#
# These are the quietest bugs a port can have: nothing raises, nothing
# reads as wrong, and the verb behaves correctly on most inputs.
# --------------------------------------------------------------------------

def test_string_equality_ignores_case():
    # mooR: crates/var/src/string.rs, PartialEq goes through
    # cmp_case_insensitive.  "Foo" == "foo" is true in MOO.
    from moo.moo_builtins import moo_eq
    assert moo_eq('Foo', 'foo')
    assert not ('Foo' == 'foo')       # what Python would have done


def test_case_folding_recurses_into_lists():
    from moo.moo_builtins import moo_eq
    assert moo_eq([['A'], 'B'], [['a'], 'b'])


def test_non_strings_compare_normally():
    from moo.moo_builtins import moo_eq, moo_ne
    assert moo_eq(1, 1) and not moo_eq(1, 2)
    assert moo_ne('a', 'b')


def test_integer_division_stays_integer():
    # Python's / would give 3.5 here.
    from moo.moo_builtins import moo_div
    assert moo_div(7, 2) == 3
    assert isinstance(moo_div(7, 2), int)


def test_integer_division_truncates_toward_zero():
    # Python's // floors, so it gives -4.  MOO, like C, gives -3.
    from moo.moo_builtins import moo_div
    assert moo_div(-7, 2) == -3
    assert moo_div(7, -2) == -3
    assert -7 // 2 == -4              # what Python would have done


def test_float_division_is_still_float():
    from moo.moo_builtins import moo_div
    assert moo_div(7.0, 2) == 3.5


def test_modulo_takes_the_sign_of_the_dividend():
    # Python takes the sign of the divisor, giving 1.
    from moo.moo_builtins import moo_mod
    assert moo_mod(-7, 2) == -1
    assert moo_mod(7, -2) == 1
    assert -7 % 2 == 1                # what Python would have done


def test_division_by_zero_raises_rather_than_returning():
    import pytest
    from moo.moo_builtins import moo_div, moo_mod
    from moo.properties import MOOError
    with pytest.raises(MOOError):
        moo_div(1, 0)
    with pytest.raises(MOOError):
        moo_mod(1, 0)


def test_listset_leaves_the_original_alone():
    # MOO lists are values.  After `l2 = l1; l2[1] = 5;` l1 is unchanged.
    from moo.moo_builtins import moo_listset
    l1 = [1, 2, 3]
    l2 = moo_listset(l1, 0, 9)
    assert l1 == [1, 2, 3] and l2 == [9, 2, 3]


# --------------------------------------------------------------------------
# Scatter, loop signals and the binary-string builtins
# --------------------------------------------------------------------------

def test_scatter_fills_required_targets_before_optional_ones():
    # {?a, b, c} with two values binds b and c, not a and b.  The order of
    # the targets does not decide it; the required ones are satisfied
    # first wherever they sit.
    from moo.moo_builtins import moo_scatter
    spec = [('opt', 0), ('req',), ('req',)]
    assert moo_scatter([1, 2], spec) == [0, 1, 2]
    assert moo_scatter([1, 2, 3], spec) == [1, 2, 3]


def test_scatter_rest_takes_what_is_left_over():
    from moo.moo_builtins import moo_scatter
    spec = [('req',), ('opt', 79), ('rest',)]
    assert moo_scatter([1], spec) == [1, 79, []]
    assert moo_scatter([1, 2, 3, 4], spec) == [1, 2, [3, 4]]


def test_scatter_with_a_rest_target_in_the_middle():
    from moo.moo_builtins import moo_scatter
    spec = [('opt', 0), ('req',), ('rest',), ('req',)]
    assert moo_scatter([1, 2, 3], spec) == [1, 2, [], 3]


def test_scatter_raises_when_the_required_targets_cannot_be_filled():
    import pytest
    from moo.moo_builtins import moo_scatter
    from moo.properties import MOOError
    with pytest.raises(MOOError):
        moo_scatter([1], [('req',), ('req',)])


def test_scatter_raises_when_there_is_nowhere_to_put_the_extras():
    import pytest
    from moo.moo_builtins import moo_scatter
    from moo.properties import MOOError
    with pytest.raises(MOOError):
        moo_scatter([1, 2, 3], [('req',), ('opt', 0)])


def test_binary_strings_round_trip():
    from moo.moo_builtins import encode_binary, decode_binary
    assert decode_binary(encode_binary('AB', 10)) == ['AB', 10]
    assert decode_binary(encode_binary(0, 255)) == [0, 255]


def test_an_escaped_tilde_comes_back_inside_a_string():
    # A tilde must be *written* ~7E because it is the escape character,
    # but it is printable, so it belongs in the string run.  Treating
    # every escape as an integer would split runs MOO keeps whole.
    from moo.moo_builtins import decode_binary
    assert decode_binary('A~7EB') == ['A~B']


def test_decode_binary_fully_returns_every_byte():
    from moo.moo_builtins import decode_binary
    assert decode_binary('AB', True) == [65, 66]


def test_a_connection_option_reads_back_what_was_set():
    # The common idiom sets an option, does something, and puts it back.
    # That round-trip has to work even where the option has no effect.
    from moo.moo_builtins import set_connection_option, connection_option

    class Conn:
        moo_options = None

    conn = Conn()
    import moo.moo_builtins as mb
    real, mb._connection = mb._connection, lambda who: conn
    try:
        set_connection_option(1, 'binary', 1)
        assert connection_option(1, 'binary') == 1
        assert connection_option(1, 'never-set') == 0
    finally:
        mb._connection = real


# --------------------------------------------------------------------------
# read() -- taking a line of input from inside a verb
#
# The interesting cases are all the ones where no line arrives, because an
# input wait is the easiest place in a server to leak a thread.
# --------------------------------------------------------------------------

class _Conn:
    """Enough of a connection for the read machinery to act on."""

    def __init__(self):
        self._pending_read = None
        self._interactive_session = None
        self.sent = []

    def queue_message(self, text):
        self.sent.append(text)


def test_a_delivered_line_wakes_the_waiter():
    from moo.verb_read import PendingRead, deliver_line, has_pending_read
    conn = _Conn()
    conn._pending_read = p = PendingRead()
    assert has_pending_read(conn)
    assert deliver_line(conn, 'yes') is True
    assert p.line == 'yes'
    # The slot is cleared, so the next line is an ordinary command again.
    assert not has_pending_read(conn)


def test_a_line_with_nobody_waiting_stays_a_command():
    from moo.verb_read import deliver_line
    assert deliver_line(_Conn(), 'look') is False


def test_disconnect_fails_the_waiter_rather_than_leaving_it_parked():
    # Without this the verb waits out the full timeout holding a worker
    # for a player who has already gone.
    from moo.verb_read import PendingRead, fail_pending_reads
    conn = _Conn()
    conn._pending_read = p = PendingRead()
    fail_pending_reads(conn, 'the connection closed')
    assert p.failed == 'the connection closed'
    assert p.line is None
    assert conn._pending_read is None


def test_failing_pending_reads_is_safe_when_there_are_none():
    from moo.verb_read import fail_pending_reads
    fail_pending_reads(_Conn())          # must not raise


def test_read_outside_a_verb_says_so_rather_than_hanging():
    import pytest
    from moo.properties import MOOError
    from moo.verb_read import read
    with pytest.raises(MOOError):
        read()


def test_a_pending_read_reports_whether_a_line_arrived():
    from moo.verb_read import PendingRead
    p = PendingRead()
    assert p.wait(0.01) is False         # nothing yet
    p.deliver('hi')
    assert p.wait(0.01) is True


# --------------------------------------------------------------------------
# MOO's list builtins as functions
#
# @port expands these inline for almost every call.  They exist for the
# case it cannot expand -- `listset(@args)`, splatted, arity unknown until
# it runs -- which was falling through to call_function and failing on a
# builtin the server plainly ought to have.
# --------------------------------------------------------------------------

def test_listset_takes_moos_argument_order():
    # The value comes before the index, which is not the obvious order.
    # A splat forwards positionally, so the shim has to match MOO rather
    # than the emitter's internal convention.
    from moo.moo_builtins import listset
    assert listset([1, 2, 3], 9, 2) == [1, 9, 3]


def test_the_list_builtins_copy():
    from moo.moo_builtins import listset, listdelete, setadd
    original = [1, 2, 3]
    listset(original, 9, 1)
    listdelete(original, 1)
    setadd(original, 4)
    assert original == [1, 2, 3]


def test_listappend_goes_after_and_listinsert_before():
    from moo.moo_builtins import listappend, listinsert
    assert listappend([1, 2, 3], 9, 1) == [1, 9, 2, 3]
    assert listinsert([1, 2, 3], 9, 1) == [9, 1, 2, 3]


def test_listappend_and_listinsert_default_to_the_ends():
    from moo.moo_builtins import listappend, listinsert
    assert listappend([1, 2], 9) == [1, 2, 9]
    assert listinsert([1, 2], 9) == [9, 1, 2]


def test_setadd_membership_ignores_case_like_moos():
    from moo.moo_builtins import setadd, setremove
    assert setadd(['Foo'], 'foo') == ['Foo']
    assert setremove(['Foo', 'bar'], 'FOO') == ['bar']


def test_a_splatted_list_builtin_works():
    # The case the inline expansion cannot cover.
    from moo.moo_builtins import listset
    args = [[1, 2, 3], 9, 2]
    assert listset(*args) == [1, 9, 3]


def test_moo_in_folds_case_like_moos_equality():
    # "foo" in {"Foo"} is 1 in MOO and was 0 here.  Alias lists are what
    # this gets used on, so it failed on any capitalisation the author had
    # not anticipated.
    from moo.moo_builtins import moo_in
    assert moo_in('foo', ['Foo']) == 1
    assert ('foo' in ['Foo']) is False        # what Python would have done


def test_moo_in_returns_a_position_not_a_boolean():
    from moo.moo_builtins import moo_in
    assert moo_in('c', ['a', 'b', 'c']) == 3
    assert moo_in('z', ['a']) == 0


def test_moo_in_on_two_strings_is_a_substring_search():
    from moo.moo_builtins import moo_in
    assert moo_in('ell', 'Hello') == 2
    assert moo_in('xyz', 'Hello') == 0


def test_sysref_lookup_ignores_case():
    # MOO looks properties up without regard to case, and cores rely on
    # it: JHCore writes $List_utils and $failed_Match meaning the same
    # objects as the lower-case spellings.
    import moo.moo_builtins as mb

    class Zero:
        properties = {'List_utils': None, 'plain': None}
        List_utils = 'the object'
        plain = 'p'

    class DB:
        def get_object(self, n):
            return Zero()

    real = mb.__dict__.get('_database')
    import moo.builtins as b
    saved, b._database = b._database, DB()
    try:
        assert mb.sysobj('list_utils') == 'the object'
        assert mb.sysobj('List_utils') == 'the object'
        assert mb.sysobj('plain') == 'p'
    finally:
        b._database = saved


def test_moo_index_shifts_lists_and_strings_but_not_maps():
    from moo.moo_builtins import moo_index
    assert moo_index([10, 20, 30], 2) == 20
    assert moo_index('abc', 1) == 'a'
    assert moo_index({'alpha': 1}, 'alpha') == 1


def test_moo_index_gets_integer_map_keys_right():
    # The silent case: a string key fails loudly, an integer key would
    # have quietly returned whatever was under index-1.
    from moo.moo_builtins import moo_index
    assert moo_index({1: 'a', 3: 'c'}, 3) == 'c'
