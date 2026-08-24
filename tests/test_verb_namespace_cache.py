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

The namespace is now also *lazy*: names bind on first read through
``_LazyVerbNS.__missing__`` rather than up front.  That moves two more things
into "quiet and severe" territory, so they are pinned here too.

The eager layers were last-write-wins -- layer 5 landing on top of layer 3 is
how the ``match`` builtin beats the harvested regex object.  Lazy is
first-touch-wins, which inverts it, so a verb calling ``match(...)`` would get
a regex or a builtin depending on whether it happened to read ``dobj`` first.
Every name two layers produce has to be owned by the later one; the collision
set is recomputed from the layers themselves so a new one cannot arrive
unnoticed.

And ``__missing__`` must raise KeyError for a name it does not own, because
that is what lets the interpreter fall through to the real builtins.  Verb
code reaches ``import`` and ``open()`` today and the engine says so out loud
(see the SAFE_PYTHON_BUILTINS comment); a namespace that answered every miss
would have made this a sandbox by accident, and a broken one.
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

    # materialise(), or this compares the 18 eagerly-bound names and says
    # nothing about the 269 that matter.  A lazy namespace answers `[]`; it
    # does not answer keys() for a name nobody has read, so a test that
    # iterates one is vacuous until it forces it.  This test passed, green
    # and meaningless, the moment the namespace became lazy.
    a = build_verb_namespace(pobj=one, this=one, db=db,
                             verb_name='v1', args='', argstr='').materialise()
    b = build_verb_namespace(pobj=two, this=two, db=db,
                             verb_name='v2', args='x', argstr='x').materialise()

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


# ---------------------------------------------------------------------------
# The lazy namespace
# ---------------------------------------------------------------------------

def test_the_namespace_binds_almost_nothing_up_front(db):
    """The point of the exercise: a verb reads a median of 8 names of 337."""
    pobj = db.create_object()
    ns = build_verb_namespace(pobj=pobj, this=pobj, db=db,
                              verb_name='v', args='', argstr='')
    assert len(ns) < 25, 'eagerly bound %d names' % len(ns)
    assert len(ns.materialise()) > 300


def test_reading_a_name_is_what_binds_it(db):
    pobj = db.create_object()
    ns = build_verb_namespace(pobj=pobj, this=pobj, db=db,
                              verb_name='v', args='', argstr='')
    assert 'notify' not in ns          # dict.__contains__, no __missing__
    assert callable(ns['notify'])      # reading binds it
    assert 'notify' in ns


def test_a_lazy_namespace_matches_an_eager_one_name_for_name(db):
    """Every name, same value -- checked against the layers, not a snapshot."""
    from moo.verb_namespace import (_fill_static_verb_ns, _get_group_map,
                                    _set_parse_fallbacks)
    from moo.moo_compat import build_compat_namespace
    from moo.verb_namespace import SAFE_PYTHON_BUILTINS

    pobj = db.create_object()
    ns = build_verb_namespace(pobj=pobj, this=pobj, db=db,
                              verb_name='v', args='', argstr='').materialise()

    expected = {}
    expected.update(SAFE_PYTHON_BUILTINS)
    _set_parse_fallbacks(expected, dobjstr='', prep='', iobjstr='',
                         args='', switches=None)
    static = {}
    static.update(mb._get_builtin_ns_template())
    _fill_static_verb_ns(static)
    expected.update(static)
    expected.update(build_compat_namespace(this=pobj, verb_name='v',
                                           call_verb=ns['call_verb'], db=db))

    # Per-call closures are rebuilt every time; compare by identity elsewhere.
    per_call = PER_CALL | {'getattr', 'setattr', 'type', 'pass_', 'tell'}
    for name, value in expected.items():
        if name in per_call:
            assert name in ns
            continue
        assert ns[name] is value or ns[name] == value, name


def test_only_the_known_names_are_claimed_by_two_layers(db):
    """The ordering trap, pinned.

    A name produced by two layers has to be owned by the later one.  Two
    exist and both are understood; a third arriving silently is the failure
    this guards, because it would surface as a verb reading the wrong value
    depending on what it read first.
    """
    from moo.verb_namespace import (_BOUND_NAMES, _PARSE_NAMES, _PERM_NAMES,
                                    _get_static_verb_ns, SAFE_PYTHON_BUILTINS)
    from moo.moo_compat import build_compat_namespace

    layers = [
        ('1 safe builtins', set(SAFE_PYTHON_BUILTINS)),
        ('2b getattr/setattr', set(_PERM_NAMES)),
        ('3 parse', set(_PARSE_NAMES)),
        ('5 static', set(_get_static_verb_ns())),
        ('5 bound', set(_BOUND_NAMES)),
        ('6b compat', set(build_compat_namespace(this=object(),
                                                 verb_name='p',
                                                 call_verb=object()))),
    ]
    claimed = {}
    for label, names in layers:
        for name in names:
            claimed.setdefault(name, []).append(label)
    collisions = {n: ls for n, ls in claimed.items() if len(ls) > 1}

    known = {
        # the one the engine already documents, at _parse_verb_inst_into_namespace
        'match': ['3 parse', '5 static'],
        # MOO's type() shadows Python's
        'type': ['1 safe builtins', '2b getattr/setattr'],
    }
    # The 16 E_* values are defined in both layer 5 and layer 6b, and they are
    # NOT the same thing: layer 5 holds the bare string 'E_DIV', layer 6b holds
    # MOOError(E_DIV, 'Division by zero').  Layer 6b ran last, so the error
    # value is what a verb sees, and `except E_PROPNF` works.  Own them the
    # other way round and every ported verb catching a MOO error would be
    # handed a string instead -- quietly, and only on the failure path.
    ns = build_verb_namespace(pobj=db.create_object(), this=db.create_object(),
                              db=db, verb_name='v', args='', argstr='')
    compat = build_compat_namespace(this=object(), verb_name='p',
                                    call_verb=object())
    for name in list(collisions):
        if name.startswith('E_'):
            assert ns[name] is compat[name] or ns[name] == compat[name], (
                '%s came from layer 5, not layer 6b' % name)
            assert ns[name] != _get_static_verb_ns()[name], (
                '%s: the two layers stopped differing -- if that was '
                'deliberate, drop one definition rather than keeping two'
                % name)
            collisions.pop(name)

    assert collisions == known, (
        'a new cross-layer name collision appeared: %s -- decide which layer '
        'owns it and pin it in _get_group_map()' % sorted(set(collisions) - set(known)))


def test_the_owning_layer_wins_whatever_the_verb_reads_first(db):
    """`match` is the builtin, not the harvested regex, either way round."""
    pobj = db.create_object()
    first = build_verb_namespace(pobj=pobj, this=pobj, db=db,
                                 verb_name='v', args='', argstr='')
    assert callable(first['match'])                 # read match before dobj

    second = build_verb_namespace(pobj=pobj, this=pobj, db=db,
                                  verb_name='v', args='', argstr='')
    assert second['dobj'] == ''                     # read dobj first
    assert callable(second['match'])


def test_an_unowned_name_still_falls_through_to_the_real_builtins(db):
    """__missing__ must raise, not answer.

    `repr` and `divmod` are not in SAFE_PYTHON_BUILTINS and never were: verb
    code reaches them through the real builtins, and so do `import` and
    `open()`.  A namespace that swallowed the miss would break every verb
    using an unshadowed builtin, and would do it silently.
    """
    pobj = db.create_object()
    ns = build_verb_namespace(pobj=pobj, this=pobj, db=db,
                              verb_name='v', args='', argstr='')
    exec(compile('a = repr((1, 2))\n'
                 'b = divmod(7, 2)\n'
                 'import os\n'
                 'c = bool(os.sep)\n'
                 'd = callable(open)', '<t>', 'exec'), ns)
    assert ns['a'] == '(1, 2)'
    assert ns['b'] == (3, 1)
    assert ns['c'] is True
    assert ns['d'] is True


def test_a_genuinely_undefined_name_is_a_NameError(db):
    pobj = db.create_object()
    ns = build_verb_namespace(pobj=pobj, this=pobj, db=db,
                              verb_name='v', args='', argstr='')
    with pytest.raises(NameError):
        exec(compile('x = no_such_name_anywhere', '<t>', 'exec'), ns)


def test_a_name_its_layer_did_not_publish_does_not_recurse(db):
    """`regex_match` is bound by the parse filler only on the instance route.

    Reading it on the fallback route must answer NameError.  Asking dict for
    it the obvious way -- ``dict.__getitem__`` -- calls ``__missing__`` again
    on a subclass, so the obvious way recurses until the stack ends.  740
    tests and a full harness transcript passed with that bug in place,
    because nothing in the starter world reads this name.
    """
    pobj = db.create_object()
    ns = build_verb_namespace(pobj=pobj, this=pobj, db=db,
                              verb_name='v', args='', argstr='')
    assert 'regex_match' not in ns.materialise()
    with pytest.raises(NameError):
        exec(compile('x = regex_match', '<t>', 'exec'), ns)


def test_extra_still_beats_every_layer(db):
    """Layer 8 was last for a reason: call_verb passes kwargs through it."""
    pobj = db.create_object()
    ns = build_verb_namespace(pobj=pobj, this=pobj, db=db, verb_name='v',
                              args='', argstr='',
                              extra={'notify': 'mine', 'dobj': 'mine too'})
    assert ns['notify'] == 'mine'
    assert ns['dobj'] == 'mine too'
    assert ns['kwargs'] == {'notify': 'mine', 'dobj': 'mine too'}
