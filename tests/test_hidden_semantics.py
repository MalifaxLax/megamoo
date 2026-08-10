"""What `hidden` on a verb means, and where that is decided.

It means "players cannot type this". Internal hooks (`wear_`,
`at_post_move`) are reached by name from engine code, so a hidden verb
must still be callable that way -- otherwise marking one breaks whatever
calls it.

The check used to live in `MOOObject.find_verb`, which every caller
shares, so `hidden` meant "unreachable by anything at all". Hiding
`rlook` cost staff the builder view for exactly that reason: `look`'s own
`call_verb` started failing and fell through its `except`.

The first attempt at a fix kept the filter in `find_verb` behind an
`include_hidden` opt-in. That was the wrong shape -- policy embedded in a
resolution primitive, which every internal caller then has to remember,
and the one that forgets fails silently. `find_verb` now resolves and
does not judge; `may_invoke` decides, weighing `hidden` and `auth`
together so the dispatch sites cannot enforce one and miss the other.
"""
import inspect
from types import SimpleNamespace

import pytest

from moo.objects import MOOObject
from moo.parser import may_invoke
from moo.verbs import VerbDef


def _obj_with(hidden):
    o = MOOObject(objnum=42, parent=None)
    o.verbs = [VerbDef(names=['wear_'], code='return 1', owner=0,
                       hidden=hidden)]
    o._inheritance_cache_valid = False
    o._resolved_verbs = None
    return o


# ------------------------------------------------------------------
# find_verb resolves; it does not judge
# ------------------------------------------------------------------

def test_find_verb_returns_a_hidden_verb():
    """Resolution is not permission. Engine callers need what is there."""
    objnum, verb = _obj_with(True).find_verb('wear_')

    assert verb is not None and verb.names == ['wear_']


def test_find_verb_returns_a_visible_verb():
    assert _obj_with(False).find_verb('wear_')[1] is not None


def test_find_verb_takes_no_hidden_parameter():
    """The opt-in is gone -- policy does not belong in the resolver.

    An `include_hidden` flag means every internal caller has to remember
    it, and a caller that forgets gets a hook that silently stops firing.
    """
    assert 'include_hidden' not in inspect.signature(MOOObject.find_verb).parameters


def test_no_caller_needs_an_opt_in_any_more():
    import moo.builtins, moo.hooks, moo.objects

    for mod in (moo.builtins, moo.hooks, moo.objects):
        assert 'include_hidden' not in inspect.getsource(mod), mod.__name__


# ------------------------------------------------------------------
# may_invoke decides
# ------------------------------------------------------------------

def test_a_hidden_verb_is_not_typeable():
    assert may_invoke(SimpleNamespace(auth=['gm5']),
                      SimpleNamespace(hidden=True, auth=0)) is False


def test_hidden_beats_even_a_wizard():
    """Not a permission level -- it is "this is not a command"."""
    assert may_invoke(SimpleNamespace(auth=['gm5']),
                      SimpleNamespace(hidden=True, auth=3)) is False


def test_a_visible_open_verb_is_typeable():
    """The accept path, or a check that refuses everything would pass."""
    assert may_invoke(SimpleNamespace(auth=None),
                      SimpleNamespace(hidden=False, auth=0)) is True


def test_a_verbdef_without_a_hidden_attribute_is_typeable():
    assert may_invoke(SimpleNamespace(auth=None), SimpleNamespace(auth=0)) is True


def test_hidden_and_auth_are_decided_in_one_place():
    """So a dispatch site cannot enforce one rule and forget the other.

    Three sites call may_invoke -- the parser and both server paths.
    Splitting the two rules across two predicates is how one of them ends
    up applied at two sites and the other at three.
    """
    src = inspect.getsource(may_invoke)

    assert 'hidden' in src and 'auth' in src


def test_the_dispatch_sites_do_not_test_hidden_themselves():
    """They must go through may_invoke, not grow their own copy.

    Scoped to the functions that actually dispatch a typed command.
    Elsewhere in server.py, `_verb_matches_file` legitimately reads
    `hidden` -- it compares a live verb against its file's declared
    metadata, which is a disk-agreement question, not a permission one.
    """
    from moo.parser import CommandParser
    from moo.server import MegaMOOServer

    dispatchers = (CommandParser._find_verb,
                   CommandParser._search_environment,
                   MegaMOOServer.execute_command,
                   MegaMOOServer._execute_task)

    for fn in dispatchers:
        # Attribute access, not the word: these docstrings discuss
        # ``hidden`` at length and should keep being able to.
        body = inspect.getsource(fn)
        assert '.hidden' not in body, (
            f'{fn.__qualname__} inspects hidden directly instead of '
            f'going through may_invoke')
