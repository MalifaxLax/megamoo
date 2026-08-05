"""
Tests for the MOO-to-Python translator.

Most of these are about *indexing*.  MOO is 1-based with inclusive ranges,
and getting that wrong produces code that runs, reads correctly, and is off
by one somewhere in a game rule months later.  Everything else the
translator does fails loudly; this does not.
"""

import ast

import pytest

from moo.moo_port import MARK, MooSyntaxError, port


def py(src):
    """Translate, and assert the result is at least valid Python."""
    r = port(src)
    body = '\n'.join(ln for ln in r.code.splitlines()
                     if not ln.strip().startswith('#'))
    if body.strip():
        # Wrapped, because verb bodies legitimately use a bare return.
        ast.parse('def _v():\n' + '\n'.join('    ' + l
                                            for l in body.splitlines()))
    return r


# --------------------------------------------------------------------------
# Indexing: the part that goes wrong silently
# --------------------------------------------------------------------------

def test_literal_index_is_shifted_and_folded():
    assert 'args[0]' in py('x = args[1];').code


def test_variable_index_is_shifted():
    assert 'args[i - 1]' in py('x = args[i];').code


def test_expression_index_is_shifted():
    r = py('x = args[i + 1];')
    assert 'args[i + 1 - 1]' in r.code


def test_range_is_half_open_on_the_right_only():
    # MOO x[2..5] is inclusive at both ends -> Python x[1:5]
    assert 'x[1:5]' in py('y = x[2..5];').code


def test_numeric_for_range_is_inclusive():
    r = py('for i in [1..3]\n  x = i;\nendfor')
    assert 'range(1, (3) + 1)' in r.code


def test_nested_index_shifts_each_level():
    r = py('x = this.stuff[i].names[1];')
    assert 'this.stuff[i - 1].names[0]' in r.code


# --------------------------------------------------------------------------
# Calls
# --------------------------------------------------------------------------

def test_tell_becomes_the_tell_builtin():
    assert 'tell(pobj, "hi")' in py('player:tell("hi");').code


def test_verb_call_becomes_call_verb():
    assert "call_verb(this, 'foo', 1, 2)" in py('this:foo(1, 2);').code


def test_verb_call_with_no_arguments():
    assert "call_verb(this, 'foo')" in py('this:foo();').code


def test_splat_argument():
    assert '*args' in py('this:foo(@args);').code


def test_notify_routes_through_msg_not_the_raw_builtin():
    # msg is a verb and overridable per object -- a deafened character
    # overrides it.  The raw notify() builtin walks straight past that.
    r = py('notify(player, "hi");')
    assert 'moo_notify(pobj, "hi")' in r.code


def test_notify_on_any_object():
    assert 'moo_notify(this, args)' in py('notify(this, args);').code


def test_notify_keeps_moos_return_value():
    # `while (!notify(conn, line, 1))` is a retry until the output buffer
    # drains.  msg() returns None, so a direct translation would spin
    # forever; moo_notify returns 1 and the loop exits at once.
    from moo.moo_builtins import moo_notify
    assert moo_notify(None, 'x') == 1


def test_notifys_no_flush_argument_is_accepted_and_ignored():
    # MOO's third argument is about an output queue this engine does not
    # have, so there is nothing for it to mean -- and nothing to warn
    # about either.
    r = py('notify(this, args, 1);')
    assert 'moo_notify(this, args, 1)' in r.code
    assert r.marks == 0


def test_length_becomes_len():
    assert 'len(x)' in py('n = length(x);').code


def test_tostr_becomes_str_concatenation():
    assert 'str(a) + str(b)' in py('s = tostr(a, b);').code


# --------------------------------------------------------------------------
# Structure
# --------------------------------------------------------------------------

def test_if_elseif_else():
    r = py('if (a)\n  x = 1;\nelseif (b)\n  x = 2;\nelse\n  x = 3;\nendif')
    assert 'if a:' in r.code and 'elif b:' in r.code and 'else:' in r.code


def test_while_loop():
    assert 'while a < 3:' in py('while (a < 3)\n  a = a + 1;\nendwhile').code


def test_for_over_a_list():
    assert 'for x in this.contents:' in py(
        'for x in (this.contents)\n  y = x;\nendfor').code


def test_list_literal_becomes_a_python_list():
    assert '[1, 2, 3]' in py('x = {1, 2, 3};').code


def test_empty_list():
    assert 'x = []' in py('x = {};').code


def test_conditional_expression():
    assert '(1 if a else 2)' in py('x = a ? 1 | 2;').code


def test_player_becomes_pobj():
    assert 'pobj' in py('x = player;').code
    assert 'player' not in py('x = player;').code.replace('pobj', '')


def test_string_utils_becomes_su():
    assert 'su.trim' in py('x = $string_utils:trim(s);').code


def test_boolean_operators():
    r = py('if (a && b || !c)\n  x = 1;\nendif')
    # Parenthesised on purpose: MOO gives && and || the same precedence,
    # Python does not, so `a && b || !c` must stay ((a and b) or not c)
    # rather than being reread as a and (b or not c).
    assert '((a and b) or not c)' in r.code


def test_and_or_keep_moo_precedence():
    # mooR's table gives || and && the same binding power, left-assoc.
    assert '((a or b) and c)' in py('x = a || b && c;').code
    assert '((a and b) or c)' in py('x = a && b || c;').code


def test_bare_string_becomes_a_comment():
    assert '# a note' in py('"a note";').code


# --------------------------------------------------------------------------
# What it refuses, and how loudly
# --------------------------------------------------------------------------

def test_backtick_becomes_a_catch():
    # mooR models this as a TryCatch *expression*.  Python has no
    # expression-level try, but deferring both halves into callables gives
    # the same semantics and stays an expression, so it still nests.
    r = py("""x = `this.foo ! E_PROPNF => 0';""")
    assert "catch(lambda: this.foo, ('E_PROPNF',), lambda: 0)" in r.code


def test_catching_e_propnf_needs_no_warning():
    # MOO raises when a property is missing; here it returns the falsy
    # sentinel and nothing is raised.  That used to be marked on every
    # backtick in the corpus; catch() recognises the sentinel instead, so
    # the translation is now simply correct.  See test_moo_libs for the
    # behaviour itself, including that a property really holding 0 keeps
    # its own value rather than taking the fallback.
    r = port("""x = `this.foo ! E_PROPNF => 5';""")
    assert r.marks == 0


def test_backtick_without_a_fallback_yields_the_error():
    # No `=>` clause: in MOO the expression evaluates to the error value,
    # which is what catch() returns when given no fallback.
    r = py("""x = `this.foo ! E_PROPNF';""")
    assert "catch(lambda: this.foo, ('E_PROPNF',))" in r.code


def test_backtick_with_several_codes():
    r = py("""x = `y ! E_PERM, E_VERBNF => 0';""")
    assert "('E_PERM', 'E_VERBNF')" in r.code


def test_backtick_nests_because_it_is_an_expression():
    # real names, so the namespace check does not flag the fixture itself
    r = py("""x = length(`args ! ANY => 0');""")
    assert 'len(catch(lambda: args' in r.code
    assert r.clean


def test_fork_becomes_a_scheduled_code_string():
    # The engine's fork() takes the deferred work as source, because a
    # scheduled task resumes on a fresh thread with no frame to re-enter.
    r = port('fork (5)\n  player:tell("later");\nendfork')
    assert r.marks == 0
    assert 'fork(5, _forked_1, dict(globals()))' in r.code
    assert 'tell(pobj, "later")' in r.code


def test_fork_keeps_the_task_id_when_one_is_named():
    # `fork tid (n)` binds the new task's id, and kill_task() is called
    # with it later, so dropping the name would break the pair.
    r = port('fork tid (0)\n  x = 1;\nendfork')
    assert 'tid = fork(0,' in r.code


def test_forked_body_is_not_indented_by_its_surroundings():
    # The body is compiled on its own, so indentation carried in from an
    # enclosing block would make it fail to parse.
    r = port('if (1)\n  fork (2)\n    x = 1;\n  endfork\nendif')
    assert '\nx = 1\n' in r.code


def test_raise_survives_inside_an_expression():
    # `perms || raise(E_PERM)` is the standard permission guard, and it is
    # an expression in MOO.  A call is an expression in Python too.
    r = port('caller_perms().wizard || raise(E_PERM);')
    assert 'moo_raise(E_PERM)' in r.code
    assert r.marks == 0


def test_caller_perms_is_not_caller():
    # The owner of the calling verb, not the calling object.  The two
    # differ, and `caller_perms().wizard` guards real permissions.
    r = port('x = caller_perms();')
    assert 'caller_perms()' in r.code


def test_assignment_to_a_property_inside_an_expression():
    r = port('if (this.name = "bob")\n  x = 1;\nendif')
    assert "moo_setprop(this, 'name', \"bob\")" in r.code
    assert r.marks == 0


def test_assignment_to_an_element_inside_an_expression():
    # MOO lists are values, so this rebinds rather than writing through.
    # The walrus does both jobs: it stores the new list and yields it,
    # which is what MOO's indexed assignment evaluates to.
    r = port('if (args[1] = 3)\n  x = 1;\nendif')
    assert '(args := moo_listset(args, 0, 3))' in r.code


def test_indexed_assignment_splits_at_the_last_bracket():
    # The container is itself an expression and may carry brackets of its
    # own, so a scan for the first `[` would split in the wrong place.
    r = port('if (args[1][2] = 3)\n  x = 1;\nendif')
    assert 'moo_listset(args[0], 1, 3)' in r.code


def test_listset_copies_rather_than_writing_through():
    # MOO's listset returns a new list; mutating would hit one the caller
    # still holds.
    r = port('x = listset(args, 9, 2);')
    assert 'moo_listset(args, 1, 9)' in r.code


def test_listset_shifts_its_index_like_any_other_subscript():
    # It was being passed straight through, which put the write one place
    # too far along -- listset(l, v, 2) touched the third element.
    assert 'moo_listset(args, 0, 9)' in port('x = listset(args, 9, 1);').code


def test_rindex_is_one_based_like_index():
    r = port('x = rindex(argstr, ".");')
    assert '(argstr.rfind(".") + 1)' in r.code


def test_try_becomes_a_python_try():
    # A statement in both languages, so it maps directly.  MOO's codes are
    # values rather than classes, so the check moves inside the handler.
    r = py('try\n  x = 1;\nexcept e (E_PROPNF)\n  x = 2;\nendtry')
    assert 'try:' in r.code
    assert 'except MOOError as e:' in r.code
    assert "if e.code not in ('E_PROPNF',):" in r.code
    assert r.clean


def test_try_with_any_catches_everything():
    r = py('try\n  x = 1;\nexcept (ANY)\n  x = 2;\nendtry')
    assert 'except MOOError' in r.code
    # ANY means no code filter at all
    assert 'not in' not in r.code


def test_a_sysref_becomes_a_lookup_on_the_system_object():
    # $foo is not special syntax in MOO -- it is #0.foo -- and this engine
    # already keeps $chair and $item there.  So there was never anything
    # to invent.
    r = port('x = $mail_agent:send();')
    assert "call_verb(sysobj('mail_agent'), 'send')" in r.code


def test_a_sysref_is_marked_when_the_database_says_it_is_absent():
    r = port('x = $mail_agent:send();', resolve=lambda n: n == 'chair')
    assert r.marks >= 1
    assert 'mail_agent' in ' '.join(r.notes)


def test_a_sysref_that_resolves_is_clean():
    r = port('x = $chair;', resolve=lambda n: n == 'chair')
    assert r.marks == 0
    assert "sysobj('chair')" in r.code


def test_without_a_database_a_sysref_is_trusted_not_accused():
    # An absent database is not evidence that an object is missing, and
    # marking on that basis would make every offline translation look
    # worse than it is.
    assert port('x = $mail_agent:send();').marks == 0


def test_assigning_to_a_sysref_sets_it_on_the_system_object():
    # `$shutdown_message = ""` is ordinary configuration; cores do it in
    # their setup verbs.  It needs a setter only because the read side is
    # a call, and Python cannot assign to one.
    r = py('$shutdown_message = "";')
    assert 'set_sysobj(\'shutdown_message\', "")' in r.code
    assert r.marks == 0


def test_clean_translation_reports_clean():
    assert port('player:tell("hi");').clean is True


def test_marked_translation_is_not_clean():
    assert port("x = `a ! ANY => 0';").clean is False


def test_marks_are_greppable():
    r = port("x = `a ! ANY => 0';")
    assert any(MARK in ln for ln in r.code.splitlines())


# --------------------------------------------------------------------------
# Failure
# --------------------------------------------------------------------------

def test_unparseable_source_raises_rather_than_half_translating():
    with pytest.raises(MooSyntaxError):
        port('if (a\n  x = 1;')


def test_garbage_raises():
    with pytest.raises(MooSyntaxError):
        port('\x00\x01\x02')


# --------------------------------------------------------------------------
# Whole verbs
# --------------------------------------------------------------------------

def test_a_realistic_verb():
    r = py('''"Give an item to someone.";
if (!dobj)
  player:tell("Give what?");
  return;
endif
for i in [1..length(player.contents)]
  item = player.contents[i];
  if (item.name == args[1])
    item:moveto(iobj);
    player:tell("You give ", item.name, " to ", iobj.name, ".");
    return 1;
  endif
endfor
player:tell("You are not carrying that.");
return 0;''')
    # `player` correctly became `pobj`, so the shift lands there
    assert 'pobj.contents[i - 1]' in r.code
    assert 'args[0]' in r.code
    assert "call_verb(item, 'moveto', iobj)" in r.code
    assert r.clean is True


# --------------------------------------------------------------------------
# Checking our own output
#
# This is the check that catches the class of bug the parse test cannot:
# valid Python that names something not there.  notify, prepstr, verb_info
# and strsub were all found by hand, one at a time, because nothing looked.
# --------------------------------------------------------------------------

def test_undefined_name_is_caught():
    from moo.moo_port import undefined_names
    assert 'wibble' in undefined_names('x = wibble(1)')


def test_verb_context_names_are_not_flagged():
    from moo.moo_port import undefined_names
    code = 'pobj.msg(argstr)\nx = this.name\ny = args[0]\nz = dobj'
    assert undefined_names(code) == []


def test_assigned_locals_are_not_flagged():
    from moo.moo_port import undefined_names
    assert undefined_names('total = 0\ntotal = total + 1') == []


def test_loop_variables_are_not_flagged():
    from moo.moo_port import undefined_names
    assert undefined_names('for item in this.contents:\n    x = item.name') == []


def test_imports_are_not_flagged():
    from moo.moo_port import undefined_names
    assert undefined_names('import json\nx = json.dumps({})') == []


def test_port_marks_a_name_it_cannot_provide():
    r = port('x = some_moo_builtin(1);')
    assert r.marks >= 1
    assert 'some_moo_builtin' in ' '.join(r.notes)
    assert not r.clean


def test_a_clean_port_never_names_the_undefined():
    from moo.moo_port import undefined_names
    r = port('player:tell("hi");\nx = length(args);')
    assert r.clean
    assert undefined_names(r.code) == []


# --------------------------------------------------------------------------
# Type tests
# --------------------------------------------------------------------------

def test_typeof_comparison_becomes_isinstance():
    assert 'isinstance(x, list)' in py('if (typeof(x) == LIST)\n y=1;\nendif').code


def test_typeof_inequality_becomes_not_isinstance():
    assert 'not isinstance(x, str)' in py('if (typeof(x) != STR)\n y=1;\nendif').code


def test_type_constants_do_not_leak_as_bare_names():
    from moo.moo_port import undefined_names
    r = port('if (typeof(x) == LIST)\n y=1;\nendif')
    assert 'LIST' not in undefined_names(r.code)


# --------------------------------------------------------------------------
# Constructs found by running the corpus, with mooR's grammar as the
# reference for precedence and for what the syntax actually means
# --------------------------------------------------------------------------

def test_computed_property_name():
    assert 'getattr(this, verb)' in py('x = this.(verb);').code


def test_computed_property_with_an_expression():
    assert 'getattr(this, verb[0:3])' in py('x = this.(verb[1..3]);').code


def test_assigning_a_computed_property_uses_setattr():
    # getattr(...) = x would not compile
    assert 'setattr(this, p, 1)' in py('this.(p) = 1;').code


def test_computed_verb_name():
    assert 'call_verb(obj, verb, *args)' in py('y = obj:(verb)(@args);').code


def test_scatter_assignment():
    assert 'a, b = args' in py('{a, b} = args;').code


def test_scatter_with_rest():
    assert 'a, *rest = args' in py('{a, @rest} = args;').code


def test_scatter_with_an_optional_expands_to_statements():
    # Python's unpacking *statement* has no optional form, but the scatter
    # does expand -- as a run of indexed assignments.  Refusing it was
    # expensive out of proportion: an unbound target is then an undefined
    # name everywhere it is read.
    r = py('{prop, ?who = caller} = args;')
    assert 'prop = args[0]' in r.code
    assert 'who = args[1] if len(args) > 1 else caller' in r.code
    assert r.marks == 0


def test_scatter_optional_without_a_default_is_none():
    # MOO leaves it genuinely unbound and raises on a read, which cannot be
    # expressed without restructuring the verb.  None is what this engine
    # uses everywhere else a value is absent.
    r = py('{?who} = args;')
    assert 'who = args[0] if len(args) > 0 else None' in r.code


def test_scatter_evaluates_its_right_side_once():
    # A call with side effects must not run once per target.
    r = py('{a, ?b = 1} = this:parse(argstr);')
    assert r.code.count("call_verb(this, 'parse'") == 1


def test_scatter_rest_follows_the_optionals():
    r = py('{who, ?indx = 1, @rest} = args;')
    assert 'rest = args[2:]' in r.code


def test_labelled_break_of_its_own_loop_is_just_break():
    # The label alone is harmless; warning on it marked every labelled
    # loop, including the great majority that break out of themselves.
    r = py('while searching (args)\n  break searching;\nendwhile')
    assert r.marks == 0
    assert 'searching' not in r.code


def test_labelled_break_of_an_enclosing_loop_unwinds_to_it():
    # Python's break leaves only the innermost loop.  Raising unwinds to
    # the right one on its own, and the handler is generated beside the
    # loop that owns the label.
    r = py('while outer (args)\n  while (args)\n    break outer;\n'
           '  endwhile\nendwhile')
    assert "raise MooLoopSignal('outer', 'break')" in r.code
    assert 'except MooLoopSignal as _sig:' in r.code
    assert r.marks == 0


def test_a_non_local_continue_wraps_the_body_not_the_loop():
    # break leaves the loop; continue has to end this iteration and start
    # the next.  Swallowing the signal inside the body does exactly that.
    r = py('while o (args)\n  for x in (args)\n    continue o;\n'
           '  endfor\nendwhile')
    lines = [l.strip() for l in r.code.splitlines()]
    assert lines.index('try:') > lines.index('while args:')
    assert r.marks == 0


def test_an_ordinary_labelled_loop_gets_no_handler():
    # MOO labels loops far more often than it jumps out of them
    # non-locally; wrapping every one would put a try around code that
    # never needed it.
    r = py('while plain (args)\n  break plain;\nendwhile')
    assert 'try:' not in r.code
    assert 'MooLoopSignal' not in r.code


def test_a_label_naming_no_open_loop_is_marked():
    r = port('while (args)\n  break nowhere;\nendwhile')
    assert r.marks >= 1


def test_the_loop_label_is_not_left_behind_as_a_statement():
    # It used to be emitted after the break: dead code, and an undefined
    # name on top of it.
    r = py('while searching (args)\n  break searching;\nendwhile')
    assert not any(l.strip() == 'searching' for l in r.code.splitlines())


def test_a_list_literal_is_still_a_list():
    # `{1, 2}` on the right of an assignment must not be read as a scatter
    assert 'x = [1, 2]' in py('x = {1, 2};').code


def test_chained_assignment():
    assert 'x = y = z = []' in py('x = y = z = {};').code


def test_dollar_is_the_length_of_the_thing_indexed():
    assert 'v[len(v) - 1]' in py('x = v[$];').code


def test_dollar_in_a_range():
    assert 'v[1:len(v)]' in py('x = v[2..$];').code


def test_return_with_assignment_becomes_two_statements():
    r = py('return this.(verb) = args[1];')
    lines = [l for l in r.code.splitlines() if l.strip() and not l.startswith('#')]
    assert lines[0] == 'setattr(this, verb, args[0])'
    assert lines[1] == 'return getattr(this, verb)'


def test_raise_as_a_statement():
    assert 'raise E_PERM' in py('raise(E_PERM);').code


def test_a_moo_variable_named_from_is_renamed():
    # `from`, `class` and `as` are ordinary variable names in MOO -- from
    # alone appears in thirteen JHCore verbs, mostly the mail system.
    r = port('from = args[1];\nx = from;')
    assert 'from_ = args[0]' in r.code and 'x = from_' in r.code


def test_the_rename_is_applied_to_reads_and_writes_alike():
    # Renaming one and not the other would turn a syntax error into a
    # verb that runs and uses the wrong variable.
    r = port('class = 1;\nclass = class + 1;')
    assert 'class ' not in r.code
    assert 'class_ = class_ + 1' in r.code


def test_a_called_name_is_not_renamed():
    # raise() is a MOO builtin whose name Python has claimed.  Renaming it
    # as though it were a variable would hide it from the branch that
    # knows what it means.
    r = port('x || raise(E_PERM);')
    assert 'moo_raise(E_PERM)' in r.code


def test_range_assignment_inside_an_expression_is_refused():
    # MOO's x[i..j] = v arrives as a Python slice, and `a:b` is not an
    # expression, so it cannot be handed to moo_setitem.
    r = port('(args[2][1..1] != "w") && (args[2][1..1] = " ");')
    assert 'moo_setitem' not in r.code
    assert r.marks >= 1


def test_assigning_to_a_true_constant_is_still_refused():
    # $nothing maps to None, which cannot be assigned to.  Unlike an
    # unknown sysref there is no property to store it on, so the line
    # becomes a comment carrying the original.
    r = py('$nothing = "";')
    assert not any(l.startswith('None = ') for l in r.code.splitlines())


def test_a_mark_from_a_helper_is_still_counted():
    # `clean` is built on the counter, and marks can be emitted by
    # module-level helpers that cannot reach it.  A verb reported clean
    # while carrying a # PORT: line is the one lie this tool must not tell.
    r = port('x = frobnicate();')
    assert not r.clean
    assert any(MARK in l for l in r.code.splitlines())


def test_a_loop_inside_a_fork_is_not_reported_as_dropped():
    # The forked body is a string in the output, so the structural check
    # cannot see its loops.  Uncounted, it accused a perfectly good
    # translation of losing them.
    r = port('fork (0)\n  while (args)\n    x = 1;\n  endwhile\nendfork')
    assert r.marks == 0
    assert not any('dropped' in n for n in r.notes)


# --------------------------------------------------------------------------
# Operators and literals found by measuring against stock LambdaCore
# --------------------------------------------------------------------------

def test_caret_is_exponentiation_not_xor():
    # mooR spells them apart -- ^ is power, ^. is xor -- precisely because
    # they would collide.  Reading ^ as xor turns every `10 ^ i` into a
    # silently wrong number.
    assert 'x = 10 ** 3' in py('x = 10 ^ 3;').code


def test_exponentiation_groups_to_the_right():
    # 2^3^2 is 2^(3^2), which Python's ** already does -- but only if the
    # parser recurses at the same level rather than the next one.
    assert 'x = 2 ** 3 ** 2' in py('x = 2 ^ 3 ^ 2;').code


def test_exponentiation_binds_tighter_than_multiplication():
    # mooR's precedence table puts Exponent above Multiplicative.
    assert 'x = 2 * 3 ** 2' in py('x = 2 * 3 ^ 2;').code


def test_scientific_notation():
    assert 'x = 1e24' in py('x = 1e24;').code
    assert 'y = 1.5e-3' in py('y = 1.5e-3;').code


def test_moor_bitwise_operators():
    # Not LambdaMOO 1.8, but a core written for mooR fails to parse at all
    # without them.
    assert 'a & 7' in py('x = a &. 7;').code
    assert 'a | 7' in py('x = a |. 7;').code
    assert 'a ^ 7' in py('x = a ^. 7;').code
    assert '1 << 23' in py('x = 1 << 23;').code


def test_maxint_is_a_constant_not_an_object():
    # real name on the left, so the namespace check does not flag the
    # fixture itself
    r = py('if (args > $maxint)\n  return 0;\nendif')
    assert '9223372036854775807' in r.code
    assert r.marks == 0


# --------------------------------------------------------------------------
# The brace ambiguity
# --------------------------------------------------------------------------

def test_a_splat_in_a_list_literal_is_not_a_scatter():
    # {@args, 1} is an ordinary list splat and very common.  Reading the
    # @ as a scatter marker cost eight points of clean rate across two
    # cores before a measurement caught it.
    r = py('x = {@args, 1};')
    assert 'x = [*args, 1]' in r.code
    assert r.marks == 0


def test_scatter_and_list_are_told_apart_by_what_follows_the_brace():
    # Only a bare `=` after the closing brace makes it an assignment.
    assert py('x = {@args} == {@args};').marks == 0


def test_scatter_inside_an_expression_binds_with_walruses():
    # LambdaCore writes `while ({?sfc, @todo} = todo)`.  Python cannot
    # bind names from a *call*, which is not the same as not being able to
    # bind inside an expression -- the walrus does, and a tuple display
    # evaluates left to right.
    r = py('while ({?a, @rest} = args)\n  x = 1;\nendwhile')
    assert '(a := _scatter_1[0]' in r.code
    assert '(rest := _scatter_1[1:])' in r.code
    assert r.marks == 0


def test_scatter_as_an_expression_evaluates_to_its_right_side():
    # MOO's scatter yields the value it was given, so the tuple ends with
    # it and is indexed [-1].
    r = py('x = ({a, b} = args);')
    assert '_scatter_1)[-1]' in r.code


def test_scatter_as_an_expression_reads_the_value_before_rebinding():
    # A rest target routinely rebinds the very name it was read from --
    # `{?sfc, @todo} = todo`.  Without a temp, the result would be the
    # list after the assignment rather than the one that was assigned.
    r = py('x = ({?a, @args} = args);')
    assert '(_scatter_1 := args)' in r.code
    assert '_scatter_1)[-1]' in r.code


# --------------------------------------------------------------------------
# Operators whose Python spelling means something else
# --------------------------------------------------------------------------

def test_string_comparison_goes_through_the_helper():
    # MOO folds case, Python does not, and `x == "north"` looks fine
    # right up until someone types "North".
    assert 'moo_eq(argstr, "north")' in py('x = (argstr == "north");').code


def test_a_numeric_operand_keeps_the_readable_spelling():
    # The two languages only disagree when *both* sides are strings, so
    # one known number is enough to make Python's operator safe.
    assert 'x = (args == 0)' in py('x = (args == 0);').code
    assert 'moo_' not in py('x = (args < 3);').code


def test_an_unknowable_comparison_is_wrapped():
    assert 'moo_eq(args, dobj)' in py('x = (args == dobj);').code


def test_division_always_goes_through_the_helper():
    # Unlike comparison, this difference is about integers, not strings,
    # so `7 / 2` -- where both operands are plainly numbers -- is exactly
    # the case that goes wrong.
    assert 'moo_div(7, 2)' in py('x = 7 / 2;').code
    assert 'moo_div(args, dobj)' in py('x = args / dobj;').code


def test_modulo_always_goes_through_the_helper():
    assert 'moo_mod(args, 4)' in py('x = args % 4;').code


# --------------------------------------------------------------------------
# MOO lists are values, not references
# --------------------------------------------------------------------------

def test_indexed_assignment_rebinds_rather_than_mutating():
    # After `l2 = l1; l2[1] = 5;` MOO leaves l1 alone.  Writing through
    # would reach into l1 as well, and only somewhere far from this line.
    assert 'args = moo_listset(args, 0, 5)' in py('args[1] = 5;').code


def test_rebinding_recurses_through_nesting():
    # a[i][j] = v must rebuild the inner list *and* store it back into the
    # outer one; rebinding only the inner mutates in place a level down.
    r = py('args[1][2] = 9;')
    assert 'args = moo_listset(args, 0, moo_listset(args[0], 1, 9))' in r.code


def test_a_property_holding_a_list_is_written_back():
    # This one matters twice over: rebinding is MOO's semantics, and it is
    # also what makes the change reach the database rather than mutating a
    # value the property still holds by reference.
    r = py('this.stuff[i] = x;')
    assert 'this.stuff = moo_listset(this.stuff, i - 1, x)' in r.code


def test_a_sysref_holding_a_list_is_written_back():
    r = py('$chair[1] = 2;')
    assert "set_sysobj('chair', moo_listset(sysobj('chair'), 0, 2))" in r.code


def test_an_unrebindable_container_is_marked():
    # Assigning into the result of a call has nowhere to store the new
    # list, so MOO's value semantics are genuinely lost -- which is worth
    # saying rather than silently writing through.
    r = port('if (this:parts()[1] = 5)\n  x = 1;\nendif')
    assert r.marks >= 1
    assert 'rebound' in ' '.join(r.notes)


def test_rebinding_in_an_expression_recurses_too():
    # The nested target has to be rebuilt inside-out and stored at the
    # outermost level; rebinding only the inner list mutates in place a
    # level down, which is the bug being avoided.
    r = py('if (args[1][2] = 3)\n  x = 1;\nendif')
    assert '(args := moo_listset(args, 0, moo_listset(args[0], 1, 3)))' in r.code


# --------------------------------------------------------------------------
# Builtins this server does not have
# --------------------------------------------------------------------------

def test_an_unknown_builtin_is_wrapped_rather_than_left_bare():
    # mooR's trick for textdump imports.  The bare name compiled and then
    # died on a NameError naming a Python identifier, which tells a MOO
    # author nothing; this keeps the verb loadable and fails, if it fails,
    # naming the builtin.
    r = port('x = frobnicate(1, 2);')
    assert "call_function('frobnicate', 1, 2)" in r.code


def test_an_unknown_builtin_with_no_arguments():
    assert "call_function('frobnicate')" in port('x = frobnicate();').code


def test_wrapping_still_marks():
    # mooR imports databases unattended, where deferring to runtime is the
    # only option.  @port has a human watching, and telling them now beats
    # telling them later.
    assert port('x = frobnicate();').marks >= 1


def test_a_known_builtin_is_not_wrapped():
    assert 'len(args)' in py('x = length(args);').code
    assert 'call_function' not in py('x = length(args);').code


def test_a_bare_undefined_name_is_not_wrapped():
    # Only names in call position are builtins.  `who` is a variable --
    # wrapping it would turn a missing value into a bogus function call.
    r = port('x = who;')
    assert 'call_function' not in r.code


def test_read_translates_now_that_it_exists():
    # It used to be refused as blocking for player input.  It still does
    # block -- on a parked thread, the way suspend() does, so the verb
    # keeps its stack and the call can be at any depth.
    r = py('answer = read(player);')
    assert 'answer = read(pobj)' in r.code
    assert r.marks == 0
