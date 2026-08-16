"""Moving an object to a different number without rebuilding it.

``@renumber`` used to serialise the object, delete its row and construct a
fresh instance from the dict.  That works, but it forks identity: the
database hands out one instance per number, so anything already holding
the object -- a running verb, a ticker subscription -- was left pointing
at the discarded copy.

``renumber_object`` moves the rows instead.  What this file pins down is
that all nine objnum-bearing columns follow, that the live instance is the
one that arrives at the new number, and -- just as important -- that
object references stored *inside* property values are deliberately left
alone.  That boundary is where LambdaMOO's ``renumber()`` draws it too,
and a future reader is owed the reason rather than a surprise.
"""
import pytest

from moo.database import Database
from moo.verb_loader import reload_verb_code


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / 'renumber.db'), mode='create')
    d.load()
    # Every world has #0, and location 0 is the "nowhere" sentinel -- so a
    # container handed #0 by an empty database can never hold anything.
    d.create_object()
    yield d
    d.close()


def _orphans(db):
    """Property and verb rows whose object no longer exists."""
    return {
        table: db._conn.execute(
            f"SELECT COUNT(*) FROM {table} "
            f"WHERE objnum NOT IN (SELECT objnum FROM objects)"
        ).fetchone()[0]
        for table in ('properties', 'verbs')
    }


def test_the_object_arrives_and_the_old_number_is_free(db):
    obj = db.create_object()
    old = obj.objnum

    db.renumber_object(old, 500)

    assert db.valid(500)
    assert not db.valid(old)


def test_the_live_instance_is_the_one_that_moves(db):
    """The whole point: identity survives, so held references keep working."""
    obj = db.create_object()
    old = obj.objnum

    db.renumber_object(old, 500)

    assert db.get_object(500) is obj
    assert obj.objnum == 500


def test_properties_and_verbs_travel_with_it(db):
    obj = db.create_object()
    obj.add_property('colour', 'blue')
    reload_verb_code(obj, 'poke', 'return 1', create=True)
    db.save_object(obj)
    old = obj.objnum

    db.renumber_object(old, 500)
    moved = db.get_object(500)

    assert moved.properties['colour'].value == 'blue'
    assert [v.names[0] for v in moved.verbs] == ['poke']
    assert _orphans(db) == {'properties': 0, 'verbs': 0}


def test_children_follow_their_parent(db):
    parent = db.create_object()
    child = db.create_object(parent=parent.objnum)
    old = parent.objnum

    db.renumber_object(old, 500)

    assert db.get_object(child.objnum).parent == 500
    assert child.objnum in db.get_object(500).children


def test_contents_follow_their_container(db):
    box = db.create_object()
    coin = db.create_object()
    coin.move_to(box, db)
    old = box.objnum

    db.renumber_object(old, 500)

    assert db.get_object(coin.objnum)._location_id == 500
    assert coin.objnum in db.get_object(500)._content_ids


def test_an_object_inside_it_moves_with_the_container(db):
    """The other direction: renumbering the thing that is *in* something."""
    box = db.create_object()
    coin = db.create_object()
    coin.move_to(box, db)
    old = coin.objnum

    db.renumber_object(old, 500)

    assert 500 in db.get_object(box.objnum)._content_ids
    assert old not in db.get_object(box.objnum)._content_ids


def test_what_it_owns_still_points_at_it(db):
    owner = db.create_object()
    owned = db.create_object(owner=owner.objnum)
    old = owner.objnum

    db.renumber_object(old, 500)

    assert db.get_object(owned.objnum).owner == 500


def test_a_login_name_follows_its_object(db):
    obj = db.create_object()
    db.add_player('bramble', obj.objnum)

    db.renumber_object(obj.objnum, 500)

    assert db.get_player('bramble') == 500


def test_references_inside_property_values_are_left_alone(db):
    """The documented boundary, not an oversight.

    ``obvexits`` holds direction indices, so [1, 2, 3] means north, south
    and east.  #0 to #9 are all real objects, so no test on a value can
    tell an index from a reference -- which is why the caller fixes a
    named list of properties afterwards and reports the rest.
    """
    room = db.create_object()
    target = db.create_object()
    room.add_property('exits', [target.objnum])
    db.save_object(room)

    db.renumber_object(target.objnum, 500)

    assert db.get_object(room.objnum).properties['exits'].value != [500]


@pytest.mark.parametrize('old, new, exc', [
    (9999, 500, KeyError),        # no such object
    (None, -1, ValueError),       # negative target
])
def test_bad_arguments_are_refused(db, old, new, exc):
    obj = db.create_object()
    with pytest.raises(exc):
        db.renumber_object(obj.objnum if old is None else old, new)


def test_an_occupied_target_is_refused(db):
    a, b = db.create_object(), db.create_object()

    with pytest.raises(ValueError):
        db.renumber_object(a.objnum, b.objnum)


def test_renumbering_to_its_own_number_is_refused(db):
    obj = db.create_object()

    with pytest.raises(ValueError):
        db.renumber_object(obj.objnum, obj.objnum)


def test_a_verb_transaction_is_committed_and_resumed(db):
    """A renumber is a commit point; the verb's deferral picks up after it.

    It cannot be part of an all-or-nothing unit -- it rewrites rows in
    every table and toggles a connection pragma, and no rollback could
    undo either.  Saying so by committing is better than a rollback that
    leaves half a renumbered database.
    """
    obj = db.create_object()
    db.begin_verb_txn()

    db.renumber_object(obj.objnum, 500)

    assert db._deferring is True
    db.commit_verb_txn()
    assert db.valid(500)


def test_the_old_number_becomes_available_again(db):
    obj = db.create_object()
    old = obj.objnum

    db.renumber_object(old, 500)

    assert old in db._index.recycled_objects
    assert 500 not in db._index.recycled_objects
