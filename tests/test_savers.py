"""A list read from a property remembers where it came from.

``obj.wear_list.insert(0, [])`` used to do nothing: reading a list-valued
property builds a new container -- it has to, because a stored ``'#5'``
resolves to a live object on the way out -- so the mutation landed on a copy
that was then discarded.  Nothing raised.

The copy stays, because it is load-bearing twice: the stored and read forms
differ, and a property may be inherited, where handing back the stored list
would let a child edit its prototype.  What changed is that the copy now
knows its object and property and writes itself back.

Two things this file is careful about.  Filling a saver during resolution
must not count as mutation, or a 49-entry read would write the property
forty-nine times.  And ``type(x) == list`` must stay True, because sixteen
verbs in the shipped worlds ask that way -- the namespaces install a
``type()`` that answers for a saver, which also makes it agree with MOO's
``typeof()``.
"""
import json

import pytest

from moo.database import Database
from moo.savers import SaverList, SaverDict, is_saver, plain


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / 'savers.db'), mode='create')
    d.load()
    d.create_object()                      # #0, so nothing lands on the sentinel
    yield d
    d.close()


@pytest.fixture
def obj(db):
    o = db.create_object()
    o.add_property('lst', [1, 2, 3])
    o.add_property('mapping', {'a': 1})
    o.add_property('tree', {'k': [1]})
    db.save_object(o)
    return o


def stored(db, obj, name):
    """The raw value as the database holds it, bypassing the read path."""
    return db.get_object(obj.objnum).properties[name].value


# ------------------------------------------------------------------
# A read comes back as a saver
# ------------------------------------------------------------------

def test_a_list_property_reads_as_a_saver(obj):
    assert is_saver(obj.lst)
    assert isinstance(obj.lst, list)


def test_a_dict_property_reads_as_a_saver(obj):
    assert is_saver(obj.mapping)
    assert isinstance(obj.mapping, dict)


def test_a_scalar_is_untouched(obj):
    obj.add_property('n', 5)
    assert obj.n == 5 and not is_saver(obj.n)


def test_reading_does_not_write(db, obj):
    """Resolution fills the container with list.append, not the saver's.

    A 49-entry property would otherwise store itself forty-nine times on
    every read.
    """
    obj._all_dirty = False
    obj.__dict__['_dirty_props'] = set()

    _ = obj.lst

    assert obj.__dict__['_dirty_props'] == set()


# ------------------------------------------------------------------
# Mutation persists
# ------------------------------------------------------------------

@pytest.mark.parametrize('mutate, expected', [
    (lambda l: l.append(4), [1, 2, 3, 4]),
    (lambda l: l.insert(0, 0), [0, 1, 2, 3]),
    (lambda l: l.extend([4, 5]), [1, 2, 3, 4, 5]),
    (lambda l: l.remove(2), [1, 3]),
    (lambda l: l.reverse(), [3, 2, 1]),
    (lambda l: l.sort(reverse=True), [3, 2, 1]),
    (lambda l: l.clear(), []),
    (lambda l: l.__setitem__(0, 9), [9, 2, 3]),
    (lambda l: l.__delitem__(0), [2, 3]),
    (lambda l: l.__setitem__(slice(0, 2), [8]), [8, 3]),
])
def test_every_list_mutation_persists(db, obj, mutate, expected):
    mutate(obj.lst)
    assert stored(db, obj, 'lst') == expected


def test_in_place_add_persists(db, obj):
    """``x += [4]`` goes through __iadd__ and has to store too."""
    lst = obj.lst
    lst += [4]
    assert stored(db, obj, 'lst') == [1, 2, 3, 4]


def test_pop_returns_its_value_and_persists(db, obj):
    assert obj.lst.pop() == 3
    assert stored(db, obj, 'lst') == [1, 2]


@pytest.mark.parametrize('mutate, expected', [
    (lambda d: d.__setitem__('b', 2), {'a': 1, 'b': 2}),
    (lambda d: d.update({'b': 2}), {'a': 1, 'b': 2}),
    (lambda d: d.setdefault('b', 2), {'a': 1, 'b': 2}),
    (lambda d: d.__delitem__('a'), {}),
    (lambda d: d.clear(), {}),
])
def test_every_dict_mutation_persists(db, obj, mutate, expected):
    mutate(obj.mapping)
    assert stored(db, obj, 'mapping') == expected


def test_a_nested_container_writes_the_root_back(db, obj):
    """``obj.tree['k'].append(2)`` has to store the whole of ``tree``."""
    obj.tree['k'].append(2)
    assert stored(db, obj, 'tree') == {'k': [1, 2]}


# ------------------------------------------------------------------
# Inheritance: mutation is copy-on-write
# ------------------------------------------------------------------

def test_mutating_an_inherited_list_does_not_touch_the_parent(db, obj):
    """The reason the copy could never simply be dropped.

    A child that declares nothing reads its parent's list.  Handing back the
    stored container would mean the child's append edited the prototype, and
    every other child with it.
    """
    child = db.create_object(parent=obj.objnum)
    assert 'lst' not in (child.properties or {})

    child.lst.append(99)

    assert 'lst' in (db.get_object(child.objnum).properties or {})
    assert stored(db, child, 'lst') == [1, 2, 3, 99]
    assert stored(db, obj, 'lst') == [1, 2, 3]


# ------------------------------------------------------------------
# A saver behaves as the thing it stands for
# ------------------------------------------------------------------

def test_reads_and_conversions_are_unchanged(obj):
    lst = obj.lst
    assert len(lst) == 3
    assert lst[0] == 1
    assert lst == [1, 2, 3]
    assert 2 in lst
    assert sorted(lst) == [1, 2, 3]
    assert list(lst) == [1, 2, 3]
    assert lst + [4] == [1, 2, 3, 4]
    assert [0] + lst == [0, 1, 2, 3]
    assert json.loads(json.dumps(lst)) == [1, 2, 3]
    assert str(lst) == '[1, 2, 3]'


def test_a_slice_is_a_plain_list(obj):
    """Nothing a saver hands onward carries a back-reference."""
    assert type(obj.lst[0:2]) is list
    assert type(list(obj.lst)) is list


def test_plain_strips_the_binding_recursively(obj):
    bare = plain(obj.tree)
    assert bare == {'k': [1]}
    assert type(bare) is dict and type(bare['k']) is list


def test_savers_do_not_reach_the_stored_value(db, obj):
    """What lands in SQLite must be ordinary JSON-able containers."""
    obj.lst.append(4)
    raw = stored(db, obj, 'lst')
    assert json.dumps(raw) == '[1, 2, 3, 4]'


# ------------------------------------------------------------------
# The type() the namespaces hand out
# ------------------------------------------------------------------

def test_moo_type_answers_for_a_saver():
    from moo.builtins import _make_moo_type
    type_ = _make_moo_type()

    assert type_(SaverList([1])) is list
    assert type_(SaverDict({'a': 1})) is dict
    assert type_(SaverList([1])) == list          # the sixteen corpus sites
    assert type_([1]) is list
    assert type_(5) is int
    assert type_('x') is str


def test_moo_type_passes_the_three_argument_form_through():
    from moo.builtins import _make_moo_type
    type_ = _make_moo_type()

    made = type_('X', (), {})
    assert isinstance(made, type)


def test_class_still_tells_the_truth():
    """type() is a convenience, not a disguise."""
    assert SaverList([1]).__class__.__name__ == 'SaverList'


def test_both_namespaces_install_it(db, obj):
    """They are assembled by different functions, which have drifted before."""
    from moo.builtins import _build_eval_globals
    from moo.verb_namespace import build_verb_namespace

    ev = _build_eval_globals({'player': obj, 'db': db})
    vb = build_verb_namespace(pobj=obj, this=obj, db=db,
                              verb_name='probe', args='', argstr='')

    for ns in (ev, vb):
        assert ns['type'] is not type
        assert ns['type'](obj.lst) is list


def test_typeof_and_type_agree(obj):
    """The inconsistency the wrapper exists to prevent."""
    from moo.moo_builtins import typeof, LIST
    from moo.builtins import _make_moo_type
    type_ = _make_moo_type()

    assert typeof(obj.lst) == LIST
    assert type_(obj.lst) == list
