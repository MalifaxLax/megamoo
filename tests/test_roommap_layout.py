"""The canonical layout must actually be computed.

`build_layout` walks every object asking whether it is a room. It asked
with a bare `obj.is_room`, and #0 -- the system object, whose parent is 0
and which therefore inherits none of #1's universal declarations -- does
not have the property. The walk reached #0 first and raised; `get_layout`
caught it, logged, and cached an empty layout.

Nothing failed loudly. Every room simply reported no coordinates, and
every mapping client fell back to dead-reckoning from the direction the
player walked -- the failure the module exists to prevent. It had never
produced a layout for any world.
"""
import pathlib

import pytest

from moo.database import Database
from moo import roommap

STARTER = (pathlib.Path(__file__).resolve().parent.parent
           / 'moo' / 'templates' / 'starter' / 'world.db')


@pytest.fixture
def world(tmp_path):
    import shutil
    copy = tmp_path / 'world.db'
    shutil.copy(STARTER, copy)
    db = Database(str(copy))
    db.load()
    roommap.invalidate()
    yield db
    roommap.invalidate()


@pytest.mark.skipif(not STARTER.is_file(), reason='starter template not present')
def test_the_layout_is_computed_rather_than_swallowed(world):
    layout = roommap.build_layout(world)
    assert layout, 'no room was placed; the walk raised and was swallowed'


@pytest.mark.skipif(not STARTER.is_file(), reason='starter template not present')
def test_asking_the_system_object_does_not_raise(world):
    """#0 is outside #1's inheritance, so it answers no universal predicate."""
    sysobj = world.get_object(0)
    assert roommap._is_room(sysobj) is False


@pytest.mark.skipif(not STARTER.is_file(), reason='starter template not present')
def test_rooms_get_coordinates(world):
    layout = roommap.build_layout(world)
    placed = [n for n in layout if roommap.coords_for(world, n)]
    assert placed, 'coords_for returned None for every room'
