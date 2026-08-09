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
