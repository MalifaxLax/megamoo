"""What `hidden` on a verb means.

It means "players cannot type this", and it has to mean only that.
Internal hooks are reached *by name* from engine code -- `call_verb`, the
hook dispatcher, attribute-style calls -- so a verb marked hidden must
still be callable that way, or marking one breaks whatever calls it.

That is not how it behaved. The filter lived in `MOOObject.find_verb`,
which every one of those callers shares, so `hidden` meant "unreachable
by anything at all" and there was no way to express "internal hook, not a
command". It cost real time twice in one day: `rlook` was hidden and
staff silently lost the builder view because `look`'s own `call_verb`
started failing, and a starter-world docstring asserted the opposite
("Hidden, so the parser will not dispatch it; call_verb still can") while
the code did the reverse.

The distinction matters beyond tidiness: ~87 internal hooks in the
shipped world are typeable, and three of them permanently corrupt the
prototype tree when typed bare. They cannot be hidden until hidden is
safe to apply.
"""
from types import SimpleNamespace

import pytest

from moo.objects import MOOObject
from moo.verbs import VerbDef


def _obj_with(hidden):
    o = MOOObject(objnum=42, parent=None)
    o.verbs = [VerbDef(names=['wear_'], code='return 1', owner=0,
                       hidden=hidden)]
    o._inheritance_cache_valid = False
    o._resolved_verbs = None
    return o


def test_a_typed_command_cannot_reach_a_hidden_verb():
    assert _obj_with(True).find_verb('wear_') == (None, None)


def test_engine_code_can_reach_a_hidden_verb():
    """The change. Without this, hiding a hook breaks its caller."""
    objnum, verb = _obj_with(True).find_verb('wear_', include_hidden=True)

    assert verb is not None and verb.names == ['wear_']


def test_a_visible_verb_is_reachable_both_ways():
    """The accept path -- or a filter that hides everything would pass."""
    o = _obj_with(False)

    assert o.find_verb('wear_')[1] is not None
    assert o.find_verb('wear_', include_hidden=True)[1] is not None


def test_filtering_is_the_default():
    """Anything that forgets to opt in keeps the safe behaviour.

    The opt-in direction is deliberate: a caller I failed to find keeps
    filtering, which is today's behaviour, rather than silently exposing
    hidden verbs to a path that should not see them.
    """
    import inspect

    sig = inspect.signature(MOOObject.find_verb)

    assert sig.parameters['include_hidden'].default is False


@pytest.mark.parametrize('caller', [
    'call_verb', 'the hook dispatcher', 'attribute-style verb calls',
])
def test_the_internal_callers_opt_in(caller):
    """Each engine path that resolves a name on its own behalf.

    Asserted against the source because these are the sites whose
    omission is invisible -- a missed one shows up as a hook that
    silently stops firing once somebody hides it.
    """
    import moo.builtins
    import moo.hooks
    import moo.objects
    import inspect

    sources = '\n'.join(inspect.getsource(m) for m in
                        (moo.builtins, moo.hooks, moo.objects))

    assert sources.count('include_hidden=True') >= 4


def test_dispatch_paths_do_not_opt_in():
    """The parser and the server must keep filtering."""
    import inspect
    import moo.parser
    import moo.server

    for mod in (moo.parser, moo.server):
        assert 'include_hidden=True' not in inspect.getsource(mod), mod.__name__
