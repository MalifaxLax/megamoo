"""What a bare name in ``eval`` / ``exec`` is allowed to resolve to.

``/ sword.name`` works because eval bmatches bare names against the
objects around you before evaluating.  The question this file pins down is
*which* objects: the room, and -- the part that regressed -- the
character's own inventory, whether or not they are standing anywhere.

Exercises ``_eval_name_candidates`` directly.  The two callers wrap their
resolution block in a bare ``except: pass``, so a fault here does not
raise, it silently stops resolving names -- which is precisely how the
inventory went missing without anything noticing.
"""
from types import SimpleNamespace

import pytest

from moo.builtins import _eval_name_candidates


def _thing(name):
    return SimpleNamespace(name=name)


def _character(contents, location=None):
    return SimpleNamespace(contents=list(contents), location=location)


def test_room_first_then_inventory():
    """Order is load-bearing: ordinals like "2 door" count the room first."""
    a, b = _thing('rug'), _thing('lamp')
    carried = _thing('sword')
    room = SimpleNamespace(contents=[a, b])

    assert _eval_name_candidates(_character([carried], room)) == [a, b, carried]


def test_inventory_included_without_a_location():
    """The regression: a character nowhere could not name what they held.

    Chargen and the isolation container put a character exactly here, and
    eval is the tool you reach for when something has gone wrong enough to
    strand one.
    """
    carried = _thing('sword')

    assert _eval_name_candidates(_character([carried])) == [carried]


def test_empty_when_nowhere_and_empty_handed():
    assert _eval_name_candidates(_character([])) == []


def test_broken_room_still_yields_inventory():
    """One side failing must not take the other with it.

    The callers swallow exceptions, so an error escaping here would
    disable all name resolution rather than lose half of it.
    """
    class _AngryRoom:
        @property
        def contents(self):
            raise RuntimeError('room is broken')

    carried = _thing('sword')

    assert _eval_name_candidates(_character([carried], _AngryRoom())) == [carried]


def test_broken_inventory_still_yields_room():
    rug = _thing('rug')

    class _AngryCharacter:
        location = SimpleNamespace(contents=[rug])

        @property
        def contents(self):
            raise RuntimeError('inventory is broken')

    assert _eval_name_candidates(_AngryCharacter()) == [rug]


def test_character_without_a_location_attribute():
    """Not every object handed to eval is a character in a room."""
    thing = SimpleNamespace(contents=[])

    assert _eval_name_candidates(thing) == []


# ------------------------------------------------------------------
# Names Python cannot parse
# ------------------------------------------------------------------
#
# `/ or` reported a syntax error while the object it named sat in the
# caller's hands. Bare names are skipped when they are Python keywords --
# otherwise `x if y else z` would try to match `if` -- so an object whose
# shortest unambiguous prefix happens to be a keyword could not be named
# at all.

import moo.builtins as _b


def _world(monkeypatch, obj_name='OrbWarsRegistry'):
    """A player carrying one object, with bmatch matching by prefix."""
    from types import SimpleNamespace
    obj = SimpleNamespace(name=obj_name, objnum=5040)
    player = SimpleNamespace(contents=[obj], location=None)

    def _bmatch(text, who, candidates, db):
        text = (text or '').strip().lower()
        if not text:
            return None
        return next((c for c in candidates if c.name.lower().startswith(text)), None)

    monkeypatch.setattr('moo.match_utils.bmatch', _bmatch)
    return obj, player


def test_a_keyword_naming_an_object_resolves(monkeypatch):
    obj, player = _world(monkeypatch)
    ns = {}

    code = _b._resolve_bare_names('or', ns, player, db=object())

    assert code != 'or'
    assert ns[code] is obj


def test_a_keyword_head_before_a_dot_resolves(monkeypatch):
    obj, player = _world(monkeypatch)
    ns = {}

    code = _b._resolve_bare_names('or.name', ns, player, db=object())

    assert code.endswith('.name') and not code.startswith('or.')
    assert ns[code.split('.')[0]] is obj


@pytest.mark.parametrize('expr', ['True', 'False', 'None'])
def test_keywords_that_are_real_expressions_are_left_alone(monkeypatch, expr):
    """`/ True` stays True even if something present answers to it.

    These are keywords, but they are also perfectly good expressions --
    which is why the test is "does this token compile on its own" rather
    than "is this token a keyword".
    """
    _, player = _world(monkeypatch, obj_name=expr)
    ns = {}

    # A real player and db, or the resolver short-circuits and this proves
    # nothing: the point is that the probe runs and declines to rewrite.
    assert _b._resolve_bare_names(expr, ns, player, db=object()) == expr


def test_an_operator_in_the_middle_is_not_rewritten(monkeypatch):
    """Only a leading token is considered.

    In `a or b` the word is the operator, and there is no way to tell it
    from a name by looking. Rewriting it would change what the expression
    means, so the boundary is deliberate: `or.name` resolves, `x = or.name`
    does not.
    """
    _, player = _world(monkeypatch)
    ns = {}
    code = 'x = or.name'

    assert _b._resolve_bare_names(code, ns, player, db=object()) == code


def test_resolution_failure_leaves_the_expression_alone(monkeypatch):
    """Matching is a convenience; it must never break eval outright."""
    _, player = _world(monkeypatch)

    def _explode(*a, **k):
        raise RuntimeError('matcher is down')

    # Patched after _world, which installs a working bmatch of its own.
    monkeypatch.setattr('moo.match_utils.bmatch', _explode)

    assert _b._resolve_bare_names('or', {}, player, db=object()) == 'or'


# ------------------------------------------------------------------
# A phrase with nothing after it
# ------------------------------------------------------------------
#
# `2 door.latchable` answered and `2 door` did not, because the multi-word
# pass was keyed on finding a dot. Asking what something *is* is the
# shorter question, and it was the one that failed.


def _phrase_world(monkeypatch, phrase='2 door'):
    """A player near one object, reachable only by a multi-word *phrase*."""
    obj = SimpleNamespace(name='a door', objnum=5013)
    player = SimpleNamespace(contents=[obj], location=None)

    def _bmatch(text, who, candidates, db):
        return obj if (text or '').strip() == phrase else None

    monkeypatch.setattr('moo.match_utils.bmatch', _bmatch)
    return obj, player


def test_a_bare_phrase_resolves(monkeypatch):
    obj, player = _phrase_world(monkeypatch)
    ns = {}

    code = _b._resolve_bare_names('2 door', ns, player, db=object())

    assert code != '2 door'
    assert ns[code] is obj


def test_a_bare_phrase_that_matches_nothing_is_reported(monkeypatch):
    """The phrase comes back, so the caller can say what it looked for.

    "invalid syntax" is a true but useless answer to `9 drapes` when there
    are four: the question was about the room, not about Python.
    """
    _, player = _phrase_world(monkeypatch, phrase='2 door')
    missed = []

    code = _b._resolve_bare_names('9 door', {}, player, db=object(),
                                  unmatched=missed)

    assert code == '9 door'
    assert missed == ['9 door']


def test_a_dotted_phrase_that_matches_nothing_is_reported_too(monkeypatch):
    _, player = _phrase_world(monkeypatch, phrase='2 door')
    missed = []

    _b._resolve_bare_names('9 door.latchable', {}, player, db=object(),
                           unmatched=missed)

    assert missed == ['9 door']


def test_arithmetic_is_not_a_phrase(monkeypatch):
    """`/ 2 + 2` is a sum, and stays one.

    Nothing is offered to the matcher unless it fails to compile on its
    own -- the same restraint the keyword pass shows for single tokens.
    """
    _, player = _phrase_world(monkeypatch, phrase='2 + 2')
    missed = []

    assert _b._resolve_bare_names('2 + 2', {}, player, db=object(),
                                  unmatched=missed) == '2 + 2'
    assert missed == []


def test_valid_python_with_a_space_is_left_alone(monkeypatch):
    """`not x` is word-shaped and compiles, so it is code, not a name."""
    _, player = _phrase_world(monkeypatch, phrase='not x')
    missed = []

    assert _b._resolve_bare_names('not x', {}, player, db=object(),
                                  unmatched=missed) == 'not x'
    assert missed == []


def test_a_real_syntax_error_keeps_its_own_message(monkeypatch):
    """Broken code must not be reported as a thing that isn't here.

    Anything carrying an operator, a bracket or a newline failed to
    compile for its own reasons, and Python's message is the useful one.
    """
    _, player = _phrase_world(monkeypatch, phrase='anything')
    missed = []
    code = 'x = 1\ny = 2 +'

    assert _b._resolve_bare_names(code, {}, player, db=object(),
                                  unmatched=missed) == code
    assert missed == []


def test_unmatched_is_optional(monkeypatch):
    """exec_python does not ask for the list, and must not have to."""
    obj, player = _phrase_world(monkeypatch)
    ns = {}

    code = _b._resolve_bare_names('2 door', ns, player, db=object())

    assert ns[code] is obj


# ------------------------------------------------------------------
# What the player actually sees
# ------------------------------------------------------------------


def _wizard(monkeypatch, phrase='2 door'):
    _, player = _phrase_world(monkeypatch, phrase=phrase)
    player.objnum = 52
    player.has_flag = lambda flag: True
    return player


def test_eval_reports_a_miss_as_a_miss(monkeypatch):
    player = _wizard(monkeypatch)

    with pytest.raises(NameError, match=r"I don't see '9 door' here\."):
        _b.eval_python('9 door', {'player': player, 'db': object()})


def test_eval_still_reports_broken_code_as_broken(monkeypatch):
    """A miss must not become the explanation for every syntax error."""
    player = _wizard(monkeypatch)

    with pytest.raises(SyntaxError):
        _b.eval_python('2 +', {'player': player, 'db': object()})
