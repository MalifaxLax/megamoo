"""The verb namespace is built once and copied, and that has to stay safe.

``build_verb_namespace`` was 69.75us of an 81.52us verb dispatch, and 74% of
that was ``_inject_moo_builtins`` -- two ``__all__`` loops issuing one
``getattr`` per name, 117 attribute lookups on every verb the server ran.  Of
the 337 names a namespace ends up with, 315 were the same object call to call,
so the invariant part is now built once and copied in.

The danger the cache introduces is quiet and severe: bind anything that closes
over the *caller* into the static half, and the first player's binding is handed
to every verb the server runs afterwards.  Nothing raises.  A staff verb would
simply run with someone else's permissions.

So these tests pin the boundary rather than the speed.  Exactly three names may
vary between calls, and the cached dict must never be reachable for mutation.
"""
import os
import tempfile

import pytest

from moo import builtins as mb
from moo.database import Database
from moo.verb_namespace import (
    _fill_static_verb_ns,
    _get_static_verb_ns,
    _inject_moo_builtins,
    build_verb_namespace,
)

# The only names allowed to differ from one verb call to the next: each closes
# over the calling player or the database instance.
PER_CALL = {'call_verb', 'search', 'find'}


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / 'ns.db'), mode='create')
    d.load()
    d.create_object()  # claim #0
    yield d
    d.close()


def _rebuilt_the_old_way(db, pobj):
    """What the pre-cache code produced, reconstructed."""
    ns = {}
    ns.update(mb._get_builtin_ns_template())
    _fill_static_verb_ns(ns)
    ns['call_verb'] = mb.make_call_verb(pobj, db)
    ns['search'] = lambda *a, _db=db, **kw: mb._search_fn(*a, db=_db, **kw)
    ns['find'] = lambda *a, _db=db, **kw: mb._find_fn(*a, db=_db, **kw)
    return ns


def test_caching_changed_nothing_a_verb_can_see(db):
    pobj = db.create_object()

    cached = {}
    _inject_moo_builtins(cached, pobj, db)
    fresh = _rebuilt_the_old_way(db, pobj)

    assert set(cached) == set(fresh)
    differing = {k for k in cached if cached[k] is not fresh[k]}
    assert differing == PER_CALL


def test_only_three_names_vary_between_callers(db):
    """The one that matters: nothing in the static half may close over a player."""
    one, two = db.create_object(), db.create_object()

    a = build_verb_namespace(pobj=one, this=one, db=db,
                             verb_name='v1', args='', argstr='')
    b = build_verb_namespace(pobj=two, this=two, db=db,
                             verb_name='v2', args='x', argstr='x')

    shared = set(a) & set(b)
    varying = {k for k in shared if a[k] is not b[k]}

    # Names build_verb_namespace itself varies, above the injected layer.
    from_the_call = {
        'pobj', 'player', 'this', 'location', 'verb', 'args', 'argstr', 'argv',
        'arglist', 'dobjlist', 'dobjlist2', 'iobjlist', 'preplist', 'switches',
        'kwargs', 'getattr', 'setattr', 'type', 'pass_',
    }
    leaked = varying - PER_CALL - from_the_call
    assert not leaked, f"per-call state reached the static namespace: {sorted(leaked)}"


def test_the_cached_dict_is_not_handed_out(db):
    """A verb mutating its namespace must not corrupt every later verb."""
    pobj = db.create_object()
    static = _get_static_verb_ns()
    before = len(static)

    ns = {}
    _inject_moo_builtins(ns, pobj, db)
    ns['notify'] = 'clobbered by a verb'
    ns['brand_new_name'] = 1

    assert _get_static_verb_ns() is static
    assert len(static) == before
    assert 'brand_new_name' not in static
    assert static['notify'] is not 'clobbered by a verb'


def test_the_cache_is_stable_across_calls(db):
    assert _get_static_verb_ns() is _get_static_verb_ns()
