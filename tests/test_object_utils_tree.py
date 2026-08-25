"""`descendants()` answers the question `@kids` was written to ask.

It answered `[]` for every object in the world, and did it silently.
`children` holds object *numbers*; the walk did `getattr(node, 'objnum',
None)` and skipped the node when that came back None, which for an int it
always does.  So the queue drained without ever appending anything.

`leaves()` is built on it and was empty for the same reason.  The tell was in
the game, not the tests: `moo verbs/50/_td_dump.py` carries a hand-written
copy of the same walk with the resolving line in it, because somebody needed
this to work and found that it did not.
"""
import pytest

from moo.builtins import set_database
from moo.database import Database
from moo.object_utils import ancestors, descendants, leaves


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / 'tree.db'), mode='create')
    d.load()
    d.create_object()          # claim #0
    # Registered globally, because `ancestors()` resolves an int parent through
    # `moo.builtins._database` rather than through the object's own handle.
    # moo/testing.py warns about exactly this: forget it and `valid()` says
    # False for everything.  Here it made ancestors() return [] and the
    # inverse-of-descendants property vacuously fail.
    set_database(d)
    yield d
    d.close()


def _tree(db):
    """root -> a -> (a1, a2), root -> b."""
    root = db.create_object()
    a = db.create_object(); a.parent = root.objnum
    b = db.create_object(); b.parent = root.objnum
    a1 = db.create_object(); a1.parent = a.objnum
    a2 = db.create_object(); a2.parent = a.objnum
    return root, a, b, a1, a2


def test_descendants_finds_children_stored_as_numbers(db):
    root, a, b, a1, a2 = _tree(db)
    assert {o.objnum for o in descendants(root)} == {a.objnum, b.objnum,
                                                     a1.objnum, a2.objnum}


def test_descendants_is_the_inverse_of_ancestors(db):
    """The property that makes the answer checkable without trusting either."""
    root, a, b, a1, a2 = _tree(db)
    for obj in descendants(root):
        assert root.objnum in [x.objnum for x in ancestors(obj)]


def test_descendants_is_breadth_first(db):
    root, a, b, a1, a2 = _tree(db)
    order = [o.objnum for o in descendants(root)]
    assert order.index(a.objnum) < order.index(a1.objnum)
    assert order.index(b.objnum) < order.index(a1.objnum)


def test_a_childless_object_has_no_descendants(db):
    root, a, b, a1, a2 = _tree(db)
    assert descendants(a1) == []


def test_leaves_are_the_childless_descendants(db):
    root, a, b, a1, a2 = _tree(db)
    assert {o.objnum for o in leaves(root)} == {b.objnum, a1.objnum, a2.objnum}


def test_a_recycled_child_is_skipped_rather_than_raising(db):
    """A stale entry in `children` is a thing that happens.  Answering about
    the rest of the family beats refusing to answer at all."""
    root, a, b, a1, a2 = _tree(db)
    kids = set(root.children or ())
    kids.add(999999)                      # names nothing
    root.children = kids
    found = {o.objnum for o in descendants(root)}
    assert found == {a.objnum, b.objnum, a1.objnum, a2.objnum}
