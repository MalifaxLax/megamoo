"""A freed number that the act of freeing it kept out of circulation.

``create_object`` will not reissue a recycled number while something still
mentions it as a bare integer, because a plain int in a list cannot be told
apart from a stored objnum.  That caution is right in general and costs
nothing in practice -- the guard only ever runs on recycled candidates, so
an ordinary numeric list has to collide with a freed number by accident.

``free_obj`` collides on purpose.  ``@freeon/set <start> to <end>`` records
the range it is about to release, so ``@freeon/set #60 to #60`` writes
``[60, 60]`` and then blocks the single number it was asked to hand back.
The narrower the range, the more completely it defeats itself.  These tests
pin the exemption that fixes it, and the general caution it must not weaken.
"""
import pytest

from moo.database import Database, NON_REF_PROPERTIES


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / 'reuse.db'), mode='create')
    d.load()
    d.create_object()  # claim #0; location 0 is the "nowhere" sentinel
    yield d
    d.close()


def _recycle(db, obj):
    """Delete an object and mark its number reusable."""
    num = obj.objnum
    db.recycle_object(num)
    return num


def test_free_obj_does_not_block_the_number_it_names(db):
    holder = db.create_object()
    doomed = db.create_object()
    num = _recycle(db, doomed)

    # Exactly what @freeon/set #N to #N stores.
    holder.add_property('free_obj', [num, num])
    db.save_object(holder)

    assert db._lingering_refs(num) == []
    assert db._refs_block_reuse(num) is False
    assert db.create_object().objnum == num


def test_an_ordinary_list_still_blocks(db):
    holder = db.create_object()
    doomed = db.create_object()
    num = _recycle(db, doomed)

    # Same shape, a name with no exemption: the caution must survive.
    holder.add_property('crew', [num])
    db.save_object(holder)

    assert (holder.objnum, 'crew') in db._lingering_refs(num)
    assert db._refs_block_reuse(num) is True
    assert db.create_object().objnum != num


def test_the_exemption_is_narrow(db):
    """One name, so a future addition is a deliberate act, not a drift."""
    assert NON_REF_PROPERTIES == frozenset({'free_obj'})
