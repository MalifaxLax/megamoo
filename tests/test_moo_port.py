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


def test_notify_becomes_msg_not_a_raw_call():
    # msg is a verb and overridable per object -- a deafened character
    # overrides it.  notify() walks straight past that, so a port must not
    # leave it in place.
    r = py('notify(player, "hi");')
    assert 'pobj.msg("hi")' in r.code
    assert 'notify' not in r.code


def test_notify_on_any_object():
    assert 'this.msg(x)' in py('notify(this, x);').code


def test_notify_with_extra_arguments_is_marked():
    r = port('notify(player, "hi", 1);')
    assert 'pobj.msg("hi")' in r.code
    assert r.marks >= 1


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
    assert 'a and b or not c' in r.code


def test_bare_string_becomes_a_comment():
    assert '# a note' in py('"a note";').code


# --------------------------------------------------------------------------
# What it refuses, and how loudly
# --------------------------------------------------------------------------

def test_backtick_is_marked_not_guessed():
    r = port("""x = `this.foo ! E_PROPNF => 0';""")
    assert r.marks == 1
    assert MARK in r.code
    # not approximated into a try block...
    body = [l for l in r.code.splitlines() if not l.strip().startswith('#')]
    assert not any('try' in l for l in body)
    # ...and the original is preserved in the notes the header reproduces
    assert 'E_PROPNF' in r.code


def test_fork_is_marked_not_guessed():
    r = port('fork (5)\n  player:tell("later");\nendfork')
    assert r.marks == 1
    assert 'delay()' in ' '.join(r.notes)


def test_try_is_marked():
    r = port('try\n  x = 1;\nexcept (ANY)\n  x = 2;\nendtry')
    assert r.marks >= 1


def test_unknown_sysref_is_marked_rather_than_invented():
    r = port('x = $mail_agent:send();')
    assert r.marks >= 1
    assert 'mail_agent' in ' '.join(r.notes)


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
