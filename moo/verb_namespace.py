"""
Unified Verb Namespace Builder for MegaMOO

This module is the **single source of truth** for constructing the
namespace dict that is passed to ``exec()`` when running verb code.
Every verb execution site in the codebase uses :func:`build_verb_namespace`
to build this dict, ensuring that builtins, context variables, and
utilities are always consistent regardless of the call path.

Call sites that use this module
-------------------------------

* ``MegaMOOServer.execute_command()`` in server.py -- top-level command
  execution for player input.
* ``VerbExecutor._create_namespace()`` in verbs.py -- verb execution
  from the verb worker system.
* ``make_call_verb()`` closure in builtins.py -- verb-calling-verb
  chains (``call_verb(obj, 'verb_name')``).

Namespace contents
------------------

The namespace dict produced by :func:`build_verb_namespace` contains:

1. **Python builtins** -- a working set of Python's builtin functions
   (``len``, ``str``, ``range``, ``sorted``, etc.), plus
   permission-checking replacements for ``getattr`` and ``setattr``.
   This is *not* a sandbox: ``__builtins__`` is left unpinned, so verb
   code can ``import``, call ``open()``, and reach anything Python
   offers.  See the note above ``SAFE_PYTHON_BUILTINS`` below -- the
   security boundary is the gm3 gate on who may write a verb, not what
   a verb may do.

2. **Core context variables** -- ``pobj`` (player), ``this`` (object
   the verb is defined on), ``caller``, ``location``, ``db``, ``verb``,
   ``args``, ``argstr``.

3. **Parsed command parts** -- ``dobj``, ``prep``, ``iobj``,
   ``switches``, ``lhs``/``rhs``, ``arglist``, etc., populated by the
   verb type's ``parse()`` method (see ``verb_types.py``).

4. **MOO builtins** -- game-specific functions like ``notify()``,
   ``move()``, ``msg_room()``, ``call_verb()``, ``search()``,
   ``find()``.

5. **Utility modules** -- ``su`` (string utilities), ``_effects``
   (visual effects manager).

6. **Messaging defaults** -- ``sub``, ``dob``, ``iob``, ``uob``,
   ``exclude`` (all default to ``None``; used by messaging builtins).

Copyright (c) 2026
License: MIT
"""

from typing import Any, Dict, List, Optional


# =============================================================================
# Python Builtins exposed to verb code
# =============================================================================
#
# The UNION of every Python builtin that was exposed by any of the three
# former namespace builders (server.py, verbs.py, builtins.py).
#
# THIS IS NOT A SANDBOX. Read the following before adding to it.
#
# These names are merged into the verb's *globals*. Nothing pins
# ``__builtins__``, so when ``exec(code, namespace)`` runs, Python inserts
# the real builtins module itself, and any name this dict does not shadow
# resolves to the genuine article. Verb code can therefore ``import os``,
# call ``open()`` and reach ``__builtins__`` directly -- all of which it
# does today, and which the "Python is the MOO language" design intends.
#
# What this dict actually does is *shadow* a handful of names with safer
# equivalents -- notably ``getattr`` and ``setattr``, which are replaced in
# build_verb_namespace() by permission-checking wrappers. That shadowing is
# a convenience for well-behaved verb code, NOT an enforcement boundary:
# ``__builtins__['getattr']`` reaches the unchecked version.
#
# The real security boundary is who may write a verb at all. @program,
# @adverb and eval are gated at gm3, so anyone who can create verb code is
# already trusted with the database. Keep that in mind before opening
# programming to ordinary players, the way classic MOO does -- doing so
# would make property permissions advisory rather than enforced.
#
# An earlier version of this comment claimed __import__, eval, open and
# friends were "EXCLUDED for security". They are omitted from this dict,
# but that does not exclude them from the namespace, and the claim misled
# at least one reader into believing a sandbox existed.
# =============================================================================

SAFE_PYTHON_BUILTINS: Dict[str, Any] = {
    # Types / constructors
    'len': len,
    'str': str,
    'int': int,
    'float': float,
    'bool': bool,
    'list': list,
    'dict': dict,
    'set': set,
    'tuple': tuple,
    'type': type,

    # Iteration helpers
    'range': range,
    'enumerate': enumerate,
    'zip': zip,
    'map': map,
    'filter': filter,
    'reversed': reversed,

    # Aggregation / math
    'sorted': sorted,
    'sum': sum,
    'min': min,
    'max': max,
    'abs': abs,
    'round': round,
    'all': all,
    'any': any,

    # Introspection
    'isinstance': isinstance,
    # NOTE: hasattr, getattr, and setattr are NOT included here.  They are
    # injected as permission-checking wrappers by build_verb_namespace()
    # so that verb code cannot bypass the MOO property permission system.

    # I/O
    'print': print,
}


# =============================================================================
# Internal Helpers -- Permission-Checking getattr / setattr Wrappers
# =============================================================================

_SENTINEL = object()


def _make_safe_getattr(pobj, db):
    """
    Return a ``getattr`` replacement that enforces MOO property read
    permissions when the target is a MOOObject.

    For non-MOOObject targets (plain Python objects, dicts, etc.) the
    wrapper delegates to the builtin ``getattr`` unchanged.
    """
    from .objects import MOOObject

    is_wizard = getattr(pobj, 'is_wizard', False)
    pobj_num = pobj.objnum

    def safe_getattr(obj, name, default=_SENTINEL):
        # Non-MOO objects: pass through to builtin
        if not isinstance(obj, MOOObject):
            if default is _SENTINEL:
                return getattr(obj, name)
            return getattr(obj, name, default)

        # Dunder / private attrs: pass through (never MOO properties)
        if name.startswith('_'):
            if default is _SENTINEL:
                return getattr(obj, name)
            return getattr(obj, name, default)

        # Check read permission on the property
        try:
            prop_info = obj.get_property_info(name, db)
            if not prop_info.can_read(pobj_num, is_wizard):
                raise PermissionError(
                    f"Permission denied: cannot read '{name}' on #{obj.objnum}"
                )
        except KeyError:
            # Property doesn't exist — let normal getattr handle it
            # (may return a verb callable or _null_attr)
            pass

        if default is _SENTINEL:
            return getattr(obj, name)
        return getattr(obj, name, default)

    return safe_getattr


def _make_safe_setattr(pobj, db):
    """
    Return a ``setattr`` replacement that enforces MOO property write
    permissions when the target is a MOOObject.

    For non-MOOObject targets the wrapper delegates to the builtin
    ``setattr`` unchanged.
    """
    from .objects import MOOObject

    is_wizard = getattr(pobj, 'is_wizard', False)
    pobj_num = pobj.objnum

    def safe_setattr(obj, name, value):
        # Non-MOO objects: pass through to builtin
        if not isinstance(obj, MOOObject):
            return setattr(obj, name, value)

        # Dunder / private attrs: pass through
        if name.startswith('_'):
            return setattr(obj, name, value)

        # `obj.x = v` is checked too now, in MOOObject.__setattr__, and
        # it asks a different question than the code below did: it holds
        # the *verb owner* to account rather than whoever typed the
        # command.  Two forms of the same write answering differently is
        # what made this checkable path unusable in the first place, so
        # defer to it -- the assignment underneath is the same one, and
        # it raises for itself.
        #
        # Native attrs and the special names still route here, because
        # __setattr__ only guards the two that escalate (flags, owner);
        # the object-owner rule below is the right one for the rest.
        if name in MOOObject._NATIVE_ATTRS or name in ('contents', 'location', 'parent'):
            if name in MOOObject._PRIVILEGED_ATTRS:
                return setattr(obj, name, value)      # __setattr__ decides
            if is_wizard or obj.owner == pobj_num:
                return setattr(obj, name, value)
            raise PermissionError(
                f"Permission denied: cannot set '{name}' on #{obj.objnum}"
            )

        return setattr(obj, name, value)

    return safe_setattr


# =============================================================================
# Internal Helpers -- Parse Result Extraction
# =============================================================================

def _parse_verb_inst_into_namespace(verb_inst, namespace: Dict[str, Any]) -> None:
    """
    Extract parsed command parts from a verb-type instance into *namespace*.

    After ``MasterVerb.parse()`` has been called on *verb_inst*, this
    function copies all the parsed attributes (dobj, prep, iobj,
    switches, lhs/rhs, etc.) into the namespace dict so they are
    available to verb code.

    If *verb_inst* is ``None``, the namespace is not modified (the
    caller should populate fallback values via
    :func:`_set_parse_fallbacks` instead).

    Args:
        verb_inst: A parsed verb-type instance (e.g. ``MasterVerb``),
            or ``None``.
        namespace: The namespace dict to populate.
    """
    if verb_inst is None:
        return

    # Direct object
    namespace['dobj'] = getattr(verb_inst, 'dobj', '') or ''
    namespace['dobjstr'] = namespace['dobj']
    namespace['dobjlist'] = getattr(verb_inst, 'dobjlist', [])

    # Preposition
    namespace['prep'] = getattr(verb_inst, 'prep', '') or ''
    namespace['preplist'] = getattr(verb_inst, 'preplist', [])

    # Indirect object
    namespace['iobj'] = getattr(verb_inst, 'iobj', '') or ''
    namespace['iobjstr'] = namespace['iobj']
    namespace['iobjlist'] = getattr(verb_inst, 'iobjlist', [])

    # Second preposition / direct object (for multi-prep commands)
    namespace['dobj2'] = getattr(verb_inst, 'dobj2', '') or ''
    namespace['dobjlist2'] = getattr(verb_inst, 'dobjlist2', [])
    namespace['prep2'] = getattr(verb_inst, 'prep2', '') or ''

    # Left-hand side / right-hand side of the preposition
    namespace['lhs'] = getattr(verb_inst, 'lhs', '') or ''
    namespace['rhs'] = getattr(verb_inst, 'rhs', '') or ''

    # Word list and regex match
    namespace['arglist'] = getattr(verb_inst, 'arglist', [])
    # Published as `regex_match`, not `match`.
    #
    # `match` is also the name of an object-matching builtin, and layer 5
    # (_inject_moo_builtins) runs after this one -- so the regex match
    # object harvested here was overwritten every time, and a verb author
    # following MasterVerb's docstring got a callable instead. It is the
    # only harvested name that collides with a builtin.
    #
    # `match` is still set below for the docstring's sake, but *before*
    # the builtins land, so the builtin continues to win and nothing that
    # calls match(...) changes behaviour. Code that wants the regex asks
    # for regex_match and gets it.
    namespace['regex_match'] = getattr(verb_inst, 'match', None)
    namespace['match'] = getattr(verb_inst, 'match', None)

    # MUSH-style switches (e.g. @create/quiet)
    namespace['switches'] = getattr(verb_inst, 'switches', [])


def _set_parse_fallbacks(namespace: Dict[str, Any], *,
                         dobjstr: str = '',
                         prep: str = '',
                         iobjstr: str = '',
                         args: str = '',
                         switches: Optional[list] = None) -> None:
    """
    Populate parse-result keys with simple string-split fallbacks.

    This is called when the verb-type instance could not be created
    (e.g. the verb has no ``parent_type``, or ``parse()`` failed).
    It provides the same keys as :func:`_parse_verb_inst_into_namespace`
    but with simpler values derived from the raw strings.

    Args:
        namespace: The namespace dict to populate.
        dobjstr:   Direct-object string (or empty).
        prep:      Preposition string (or empty).
        iobjstr:   Indirect-object string (or empty).
        args:      Raw argument string for building ``arglist``.
        switches:  List of switches (or ``None`` for empty list).
    """
    namespace['dobj'] = dobjstr
    namespace['dobjstr'] = dobjstr
    namespace['dobjlist'] = dobjstr.split() if dobjstr else []
    namespace['prep'] = prep
    namespace['preplist'] = prep.split() if prep else []
    namespace['iobj'] = iobjstr
    namespace['iobjstr'] = iobjstr
    namespace['iobjlist'] = iobjstr.split() if iobjstr else []
    namespace['dobj2'] = ''
    namespace['dobjlist2'] = []
    namespace['prep2'] = ''
    namespace['lhs'] = ''
    namespace['rhs'] = ''
    namespace['arglist'] = args.split() if args else []
    namespace['match'] = None
    namespace['switches'] = switches if switches is not None else []


# =============================================================================
# Internal Helpers -- Verb Type Instantiation
# =============================================================================

def _verb_type_needs_instance(verb_def) -> bool:
    """Whether this verb's type wants an instance built for the call.

    A verb that is called rather than typed has no command line to parse and
    no typed command to veto, so ``FunctionVerb`` declares
    ``needs_instance = False`` and the construction is skipped -- 2.06us of a
    6.02us call, measured.

    Fails *towards* building one.  An unresolvable ``parent_type`` is already
    survivable (``_instantiate_verb_type`` logs and returns None, and the
    namespace falls back to string splitting); deciding to skip on the
    strength of a type we could not load would turn a recoverable
    misconfiguration into a silently different parse.
    """
    path = getattr(verb_def, 'parent_type', None)
    if not path:
        return True
    try:
        from .verb_types import resolve_verb_type
        return bool(getattr(resolve_verb_type(path), 'needs_instance', True))
    except Exception:
        return True


def _instantiate_verb_type(verb_def, pobj, this_obj, location, db,
                           verb_name: str, args: str,
                           injected_switches=None):
    """
    Instantiate the verb's parent class, populate its runtime context,
    run ``at_pre_cmd()`` and ``parse()``, and return the instance.

    This bridges the verb definition (stored in the database) and the
    verb-type class (defined in ``verb_types.py``).  The verb_def's
    ``parent_type`` attribute is resolved to a class, an instance is
    created, and its ``parse()`` method is called to populate the
    structured command parts (dobj, prep, iobj, etc.).

    ``at_pre_cmd()`` runs first, before parsing, as its docstring has
    always promised -- which is what makes it the place for a check
    that should abort without the cost of parsing, and equally why the
    parsed slots are not available to it yet.  Returning ``True``
    vetoes the command: the flag is recorded on the instance as
    ``_vetoed`` and the execution sites skip the verb body (see
    :func:`verb_body_vetoed`).

    A hook that raises is logged and otherwise ignored -- the command
    proceeds.  Failing open matches the rest of the verb system (a
    broken ``parse()`` falls back to string splitting rather than
    killing the command), and the alternative is that one typo in a
    shared verb type silently swallows every command using it.

    Args:
        verb_def:           The verb definition object (with a
                            ``parent_type`` attribute).
        pobj:               Player object executing the verb.
        this_obj:           The MOO object the verb is defined on.
        location:           Player's current location.
        db:                 Database instance.
        verb_name:          The verb command string.
        args:               Raw argument string.
        injected_switches:  Switches injected by ``call_verb`` switch
                            syntax (optional).

    Returns:
        The populated verb-type instance, or ``None`` if instantiation
        or parsing fails.
    """
    import logging
    logger = logging.getLogger('megamoo.verb_namespace')

    try:
        from .verb_types import resolve_verb_type
        parent_cls = resolve_verb_type(
            getattr(verb_def, 'parent_type', 'moo.verb_types.MasterVerb')
        )
        inst = parent_cls()
        inst.pobj = pobj
        inst.this = this_obj
        inst.location = location
        inst.db = db
        inst.cmdstring = verb_name
        if injected_switches is not None:
            # Store switches for MasterVerb.parse() to pick up
            inst._injected_switches = injected_switches
        inst.raw = args
        inst.args = args.strip() if args else ''

        # Lifecycle: at_pre_cmd() -> parse() -> verb body -> at_post_cmd().
        # Isolated from parsing so a broken hook cannot cost the verb its
        # parsed arguments.
        inst._vetoed = False
        try:
            inst._vetoed = bool(inst.at_pre_cmd())
        except Exception as e:
            logger.error(
                f"at_pre_cmd failed on {type(inst).__name__} "
                f"for verb '{verb_name}': {e}", exc_info=True)

        inst.parse()
        return inst
    except Exception as e:
        logger.warning(f"Verb type parse failed: {e}")
        return None


# =============================================================================
# Internal Helpers -- MOO Builtin Injection
# =============================================================================

_STATIC_VERB_NS: Optional[Dict[str, Any]] = None


def _get_static_verb_ns() -> Dict[str, Any]:
    """
    The part of the verb namespace that is identical on every call.

    Built once, then copied in.  Everything bound here is a module, a
    plain function, or a sentinel -- none of it closes over the player,
    the database, or anything else about a particular call.

    This exists because it was measured.  ``build_verb_namespace`` was
    69.75us of an 81.52us verb dispatch, and 74% of *that* was this
    function: the two ``__all__`` loops below issue one ``getattr`` per
    name, which came to 117 attribute lookups and 13 module-import
    lookups on every verb the server ran.  Of the 337 names a namespace
    ends up holding, 315 are the same object from one call to the next.

    Cached at module scope for the same reason ``_get_builtin_ns_template``
    is: a Python module change needs a server restart regardless -- verb
    reloading reads verb source from disk and never re-imports these --
    so there is no staleness window a caller could observe.
    """
    global _STATIC_VERB_NS
    if _STATIC_VERB_NS is not None:
        return _STATIC_VERB_NS

    from . import builtins as moo_builtins
    namespace: Dict[str, Any] = {}

    # Cached template of all public MOO builtins (avoids rebuilding
    # the dict on every verb execution)
    namespace.update(moo_builtins._get_builtin_ns_template())

    _fill_static_verb_ns(namespace)
    _STATIC_VERB_NS = namespace
    return namespace


def _inject_moo_builtins(namespace: Dict[str, Any], pobj, db) -> None:
    """
    Add MOO builtins, search/find helpers, string utilities, and the
    effects utility into *namespace*.

    This populates the namespace with all the game-specific functions
    that verb code can call:

    * All public MOO builtins (``notify``, ``move``, ``msg_room``, etc.)
    * ``call_verb(obj, 'verb_name')`` -- for verb-calling-verb chains
    * ``search()`` / ``find()`` -- object lookup by name/property
    * ``su`` -- string utility module
    * ``_effects`` -- visual effects manager

    Args:
        namespace: The namespace dict to populate.
        pobj:      Player object (needed to bind ``call_verb``).
        db:        Database instance (needed to bind ``search``/``find``
                   and ``call_verb``).
    """
    from . import builtins as moo_builtins

    # Everything that does not vary per call, built once.
    namespace.update(_get_static_verb_ns())

    # The three bindings that genuinely do vary: each closes over the
    # calling player or this database instance.
    #
    # Verb-calling-verb support: call_verb(obj, 'verb_name', ...)
    namespace['call_verb'] = moo_builtins.make_call_verb(pobj, db)

    # search() and find() bound to this database instance
    namespace['search'] = lambda *a, _db=db, **kw: moo_builtins._search_fn(*a, db=_db, **kw)
    namespace['find'] = lambda *a, _db=db, **kw: moo_builtins._find_fn(*a, db=_db, **kw)


def _fill_static_verb_ns(namespace: Dict[str, Any]) -> None:
    """Bind every call-invariant name into *namespace*. See
    :func:`_get_static_verb_ns` -- this runs once, not per verb."""
    # String utilities (su.wrap, su.center, su.table, etc.)
    #
    # Bound under both names: `su` is the MegaMOO spelling, `string_utils`
    # is what code ported from a MOO already says, so `$string_utils`
    # resolves without an object behind it. Same instance either way.

    # Object utilities (ou.make_object, ou.make_room, etc.)
    #
    # Bound under both names, as su is: `object_utils` is what code ported
    # from a MOO already says, so `$object_utils` resolves without an
    # object behind it.
    from . import object_utils as ou
    namespace['ou'] = ou
    namespace['object_utils'] = ou

    # The other LambdaMOO utility objects, ported far enough to carry the
    # calls a real core makes.  Same trick: the MOO spelling is an alias,
    # so ported code needs no rewriting beyond dropping the $.
    from .moo_libs import (lu, cu, cdu, pu, moo_match, moo_rmatch,
                           moo_substitute, FAILED_MATCH, AMBIGUOUS_MATCH)
    namespace['lu'] = lu
    namespace['list_utils'] = lu
    namespace['cu'] = cu
    namespace['command_utils'] = cu
    namespace['cdu'] = cdu
    namespace['code_utils'] = cdu
    namespace['pu'] = pu
    namespace['perm_utils'] = pu

    # MOO's regex builtins, under names that cannot collide.  `match` is
    # already taken here by object matching, and a ported verb calling the
    # wrong one of those would compile and then quietly misbehave, so MOO's
    # regex keeps the moo_ prefix rather than fighting for the short name.
    # MOO's read(), which parks the verb until the player types a line.
    # Bound here rather than in moo_builtins because it is engine
    # machinery -- it takes the baton off this thread -- not a
    # compatibility shim.
    from .verb_read import read as _moo_read
    namespace['read'] = _moo_read

    namespace['moo_match'] = moo_match
    namespace['moo_rmatch'] = moo_rmatch
    namespace['moo_substitute'] = moo_substitute

    # MOO's several ways of saying "no object".  $nothing and $no_one are
    # None here; the two matcher outcomes are sentinels -- see moo_libs.
    namespace['FAILED_MATCH'] = FAILED_MATCH
    namespace['AMBIGUOUS_MATCH'] = AMBIGUOUS_MATCH

    # LambdaMOO builtins that exist only for ported code.  Kept in their
    # own module rather than added to moo.builtins: several of them, most
    # obviously `random`, take the MOO spelling of a name this engine
    # already uses differently, and the two vocabularies should not have
    # to fight over it.
    # File builtins, for databases ported from a server that had them.
    # Optional: the module is not part of the base distribution, and a
    # tree without it simply does not bind these names.  Where it is
    # present the functions refuse to work until a files root is set, so a
    # server that never configured one is not exposed either way.
    try:
        from . import moo_files as _mf
        for _n in _mf.__all__:
            namespace[_n] = getattr(_mf, _n)
    except ImportError:
        pass

    from . import moo_builtins as _mb
    for _n in _mb.__all__:
        namespace[_n] = getattr(_mb, _n)



# =============================================================================
# Internal Helpers -- the lazy namespace
# =============================================================================
#
# A verb reads a median of 8 distinct global names.  The namespace holds 337.
#
# Measured by counting LOAD_GLOBAL sites across the 275 compilable verbs in
# the Shadowfall tree: mean 8.6 distinct names, median 8, p90 16, max 52.  So
# binding all 337 up front does about 97% of its work for nothing, and does it
# on every verb the server runs.  Against a 27us verb dispatch, building the
# dict was 12us of it.
#
# ``exec()`` accepts a dict *subclass* as globals.  CPython's LOAD_GLOBAL uses
# its fast path only when globals and builtins are both exact dicts; for a
# subclass it goes through ``PyObject_GetItem``, which honours ``__missing__``.
# So a name can be bound the first time the verb actually reads it.
#
# A name this class does not know raises KeyError, and the interpreter then
# falls through to the real builtins exactly as before.  That is what keeps
# ``import``, ``open()`` and every unshadowed builtin working -- read the
# SAFE_PYTHON_BUILTINS comment above: this is not a sandbox, and it must not
# become one by accident here.
#
# THE ORDERING TRAP
# -----------------
# The eager layers were last-write-wins.  Layer 5 landing on top of layer 3 is
# precisely how the ``match`` *builtin* beats the harvested regex object -- see
# the comment in _parse_verb_inst_into_namespace, which documents that as the
# one harvested name colliding with a builtin.
#
# A lazy namespace is first-touch-wins, which inverts that.  Whichever group
# the verb happens to read first would win, so a verb calling ``match(...)``
# would get a regex object or None depending on whether it had touched ``dobj``
# first.  Every name produced by more than one layer therefore has to be owned
# by exactly one group, and that group has to be the layer that used to run
# last.  _get_group_map() assigns in layer order for that reason, and the parse
# filler re-pins ``match`` on its way out.
#
# tests/test_verb_namespace_cache.py recomputes the collision set from the
# layers themselves and fails if a new name joins it.

_LAZY_STATIC = 1     # layer 5  -- the call-invariant MOO builtins
_LAZY_SAFE = 2       # layer 1  -- SAFE_PYTHON_BUILTINS
_LAZY_BOUND = 3      # layer 5  -- call_verb / search / find
_LAZY_PERM = 4       # layer 2b -- getattr / setattr / hasattr / type
_LAZY_PARSE = 5      # layer 3  -- the parsed command parts
_LAZY_COMPAT = 6     # layer 6b -- tell / pass_ / E_*
_LAZY_GLOBALS = 7    # layer 7  -- the globals module
_LAZY_SU = 8         # layer 5  -- $string_utils, resolved per database
_LAZY_EU = 9         # layer 5  -- $effects_utils, likewise

# What layer 3 publishes, by either route.  _parse_verb_inst_into_namespace
# harvests one name _set_parse_fallbacks does not (``regex_match``); a verb
# reading it on the fallback path got a NameError before and still does,
# because the filler simply does not set it and __missing__ re-raises.
_PARSE_NAMES = (
    'dobj', 'dobjstr', 'dobjlist', 'prep', 'preplist', 'iobj', 'iobjstr',
    'iobjlist', 'dobj2', 'dobjlist2', 'prep2', 'lhs', 'rhs', 'arglist',
    'regex_match', 'match', 'switches',
)
_BOUND_NAMES = ('call_verb', 'search', 'find')
#: `su` used to be the StringUtils *instance*, bound once into the static
#: namespace.  It names the $string_utils *object* now, which depends on the
#: database and so cannot be call-invariant.  Both spellings resolve to it:
#: `su` is the MegaMOO one, `string_utils` is what ported MOO code says.
_STRING_UTILS_NAMES = ('su', 'string_utils')
#: `_effects` was the Python EffectsManager instance.  Its state was already
#: on the object -- fx_registry and tickers are #53's properties, and the
#: class read and wrote them -- so only the code was ever in Python.
_EFFECTS_NAMES = ('_effects',)
_PERM_NAMES = ('getattr', 'setattr', 'hasattr', 'type')

_GROUP_OF: Optional[Dict[str, int]] = None


def _get_group_map() -> Dict[str, int]:
    """Name -> the group that binds it.  Built once, in eager layer order.

    Later layers overwrite earlier ones here for the same reason they did
    when the namespace was built eagerly: the last layer to claim a name is
    the one whose value a verb used to see.
    """
    global _GROUP_OF
    if _GROUP_OF is not None:
        return _GROUP_OF

    from .moo_compat import build_compat_namespace

    groups: Dict[str, int] = {}
    for name in SAFE_PYTHON_BUILTINS:                       # layer 1
        groups[name] = _LAZY_SAFE
    for name in _PERM_NAMES:                                # layer 2b
        groups[name] = _LAZY_PERM
    for name in _PARSE_NAMES:                               # layer 3
        groups[name] = _LAZY_PARSE
    for name in _get_static_verb_ns():                      # layer 5
        groups[name] = _LAZY_STATIC
    for name in _BOUND_NAMES:                               # layer 5
        groups[name] = _LAZY_BOUND
    for name in _STRING_UTILS_NAMES:                        # layer 5
        groups[name] = _LAZY_SU
    for name in _EFFECTS_NAMES:                             # layer 5
        groups[name] = _LAZY_EU
    # Layer 6b is probed rather than listed: moo_compat owns the set, and
    # ``pass_`` only appears when there is enough context to build it, so the
    # probe supplies that context to learn the name exists.
    for name in build_compat_namespace(this=_PROBE, verb_name='probe',
                                       call_verb=_PROBE, db=None):
        groups[name] = _LAZY_COMPAT
    groups['globals'] = _LAZY_GLOBALS                       # layer 7

    _GROUP_OF = groups
    return groups


_PROBE = object()   # stands in for `this`/`call_verb` while probing layer 6b
_ABSENT = object()  # "the filler did not bind this name"


class _LazyVerbNS(dict):
    """
    The globals a verb executes in, binding each name on first read.

    Everything a verb is handed eagerly -- ``this``, ``pobj``, ``args`` and
    the rest of the call's own context -- is written at construction.  The
    rest arrives through :meth:`__missing__`.

    It answers ``[]``.  It does *not* answer ``keys()``, ``in``, ``len()`` or
    ``items()`` for a name nobody has read yet, because those go through
    ``dict`` unchanged and see only what has been bound so far.  Verb code
    never notices; anything that wants to *inspect* a namespace has to call
    :meth:`materialise` first.
    """

    __slots__ = ('_pobj', '_db', '_this', '_verb_name', '_call_depth',
                 '_verb_inst', '_parse_args')

    def __missing__(self, key):
        groups = _GROUP_OF
        if groups is None:
            groups = _get_group_map()
        group = groups.get(key)
        if group is None:
            # Not ours.  The interpreter falls through to the real builtins,
            # and raises NameError if it is not there either -- exactly what
            # happened before anything was lazy.
            raise KeyError(key)
        if group == _LAZY_STATIC:
            value = _STATIC_VERB_NS[key]
            dict.__setitem__(self, key, value)
            return value
        if group == _LAZY_SAFE:
            value = SAFE_PYTHON_BUILTINS[key]
            dict.__setitem__(self, key, value)
            return value
        self._bind_group(group)
        # dict.get, NOT dict.__getitem__: on a dict *subclass* __getitem__
        # calls __missing__ for an absent key, so asking that way recurses
        # until the stack ends.  It is reachable -- `regex_match` is bound by
        # the parse filler only on the instance route, and a verb reading it
        # on the fallback route is exactly this case.  It has to answer the
        # way it always did, which is NameError.
        value = dict.get(self, key, _ABSENT)
        if value is _ABSENT:
            raise KeyError(key)
        return value

    def _bind_group(self, group):
        """Run one layer's filler into this namespace."""
        if group == _LAZY_BOUND:
            from . import builtins as moo_builtins
            db = self._db
            depth = self._call_depth
            dict.update(self, {
                'call_verb': (moo_builtins.make_call_verb(self._pobj, db, depth)
                              if depth else
                              moo_builtins.make_call_verb(self._pobj, db)),
                'search': lambda *a, _db=db, **kw: moo_builtins._search_fn(
                    *a, db=_db, **kw),
                'find': lambda *a, _db=db, **kw: moo_builtins._find_fn(
                    *a, db=_db, **kw),
            })
        elif group == _LAZY_PERM:
            from .builtins import _make_moo_type
            dict.update(self, {
                'getattr': _make_safe_getattr(self._pobj, self._db),
                'setattr': _make_safe_setattr(self._pobj, self._db),
                'hasattr': hasattr,
                'type': _make_moo_type(),
            })
        elif group == _LAZY_PARSE:
            if self._verb_inst is not None:
                _parse_verb_inst_into_namespace(self._verb_inst, self)
            else:
                _set_parse_fallbacks(self, **self._parse_args)
            # Layer 5 owns `match`; see THE ORDERING TRAP above.
            dict.__setitem__(self, 'match', _STATIC_VERB_NS['match'])
        elif group == _LAZY_COMPAT:
            from .moo_compat import build_compat_namespace
            dict.update(self, build_compat_namespace(
                this=self._this, verb_name=self._verb_name,
                call_verb=self['call_verb'], db=self._db))
        elif group == _LAZY_SU:
            from .object_utils import system_ref
            obj = system_ref(self._db, 'string_utils')
            if obj is None:
                return      # leave unbound -> NameError, which is the truth
            for nm in _STRING_UTILS_NAMES:
                dict.__setitem__(self, nm, obj)
        elif group == _LAZY_EU:
            from .object_utils import system_ref
            obj = system_ref(self._db, 'effects_utils')
            if obj is None:
                return
            for nm in _EFFECTS_NAMES:
                dict.__setitem__(self, nm, obj)
        elif group == _LAZY_GLOBALS:
            try:
                dict.__setitem__(
                    self, 'globals',
                    __import__('moo.globals', fromlist=['globals']))
            except Exception:
                pass

    def materialise(self):
        """Bind every name this namespace can bind, and return it.

        For tests and introspection.  A verb never needs it: verb code reads
        names, and reading is what binds them.
        """
        for name in _get_group_map():
            try:
                self[name]
            except KeyError:
                pass
        return self


# =============================================================================
# Public API -- build_verb_namespace()
# =============================================================================

def build_verb_namespace(
    *,
    pobj,
    this,
    db,
    verb_name: str,
    args: str,
    argstr: str,
    location=None,
    caller=None,
    context=None,
    verb_def=None,
    parse_result=None,
    injected_switches=None,
    call_depth: int = 0,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build the complete namespace dict for verb code execution.

    This is the **single source of truth** for namespace construction.
    All verb execution paths in the codebase call this function to
    ensure consistent variable availability in verb code.

    A verb sees the same names it always did:

    1. Safe Python builtins (``len``, ``str``, ``range``, etc.)
    2. Core context variables (``pobj``, ``this``, ``db``, etc.)
    3. Parsed command parts (``dobj``, ``prep``, ``iobj``, etc.)
    4. Messaging defaults (``sub``, ``dob``, ``iob``, ``uob``, ``exclude``)
    5. MOO builtins and utilities (``notify``, ``call_verb``, ``su``, etc.)
    6. Depth-aware ``call_verb`` override (for nested verb chains)
    7. Globals module reference
    8. Extra caller-supplied overrides (kwargs from ``call_verb``, etc.)

    They no longer all arrive up front.  Groups 1, 3, 5, 6, 7 are bound on
    first read by :class:`_LazyVerbNS`; this function eagerly binds only the
    call's own context, group 4, and group 8 -- 18 names of 337.  A verb reads
    a median of 8, so the returned object costs 1.1us to build where copying
    every layer cost 12.1us, and no verb in a 275-verb corpus is slower.

    Two consequences worth knowing:

    * The verb-type lifecycle is **not** deferred.  ``at_pre_cmd()`` and
      ``parse()`` run here, because the veto has to be decided before the body
      runs.  Only harvesting the parsed slots into names is deferred.
    * The result answers ``[]``.  It does not answer ``keys()``, ``in``,
      ``len()`` or ``items()`` for a name nobody has read yet.  Verb code
      never notices, because reading is what binds; anything *inspecting* a
      namespace must call ``.materialise()`` first.  A test that iterates one
      without it is vacuous rather than failing.

    Parameters
    ----------
    pobj : MOOObject
        The player object executing the command.
    this : MOOObject
        The object the verb is defined on.
    db : Database
        Database instance for object lookups.
    verb_name : str
        The verb being executed (e.g. ``'look'``, ``'@create'``).
    args : str
        Argument string (stripped of leading/trailing whitespace).
    argstr : str
        Raw argument string (unstripped), as typed by the player.
    location : MOOObject or None
        Player's current location.  Defaults to ``pobj.location``
        if not provided.
    caller : MOOObject or None
        The calling object in verb-calling-verb chains.  ``None`` for
        direct player commands.
    context : VerbContext or None
        Legacy context object, exposed as ``context`` in the namespace.
    verb_def : VerbDef or None
        Verb definition from the database.  If provided, the verb's
        ``parent_type`` is used to instantiate and parse the command
        through the verb-type system.
    parse_result : ParseResult or None
        Pre-parsed command result (used as fallback values when the
        verb-type instantiation fails).
    injected_switches : list or None
        MUSH-style switches injected by ``call_verb`` switch syntax
        (e.g. ``call_verb(obj, 'create/quiet')``).
    call_depth : int
        Current verb-calling-verb nesting depth.  Used to create a
        depth-aware ``call_verb`` that enforces ``MAX_VERB_DEPTH``.
    extra : dict or None
        Additional key/value pairs merged last, overriding everything.
        Used by ``call_verb`` to pass kwargs into the called verb's
        namespace.

    Returns
    -------
    _LazyVerbNS
        A ``dict`` subclass ready for ``exec(compiled_code, namespace)``.
    """
    if location is None:
        location = pobj.location

    namespace = _LazyVerbNS()
    namespace._pobj = pobj
    namespace._db = db
    namespace._this = this
    namespace._verb_name = verb_name
    namespace._call_depth = call_depth

    # --- Layer 3 (the half that cannot be deferred) ---
    # at_pre_cmd() and parse() run whether or not the body ever reads dobj:
    # the veto has to be decided before the body runs, and parse() is the
    # only engine-called hook a verb type gets.  So the instance is built
    # here and only *harvesting its results into names* is deferred.
    verb_inst = None
    if verb_def is not None and _verb_type_needs_instance(verb_def):
        verb_inst = _instantiate_verb_type(
            verb_def, pobj, this, location, db, verb_name, argstr,
            injected_switches=injected_switches,
        )

    # What the parse filler will need if there is no instance to harvest.
    fallback_dobjstr = ''
    fallback_prep = ''
    fallback_iobjstr = ''
    fallback_switches = None
    if verb_inst is None and parse_result is not None:
        fallback_dobjstr = getattr(parse_result, 'dobjstr', '') or ''
        fallback_prep = (getattr(parse_result, 'prep', '')
                         or getattr(parse_result, 'prepstr', '')
                         or '')
        fallback_iobjstr = getattr(parse_result, 'iobjstr', '') or ''
        fallback_switches = getattr(parse_result, 'switches', None)
    namespace._verb_inst = verb_inst
    namespace._parse_args = {
        'dobjstr': fallback_dobjstr,
        'prep': fallback_prep,
        'iobjstr': fallback_iobjstr,
        'args': args,
        'switches': fallback_switches,
    }

    # --- Eager: this call's own context ---
    # Every name here is either specific to this call or too cheap to defer.
    # Everything else -- the MOO builtins, the Python builtins, the parsed
    # slots, the compatibility names, the globals module -- is bound by
    # _LazyVerbNS.__missing__ the first time the verb reads it.
    dict.update(namespace, {
        'pobj': pobj,
        'player': pobj,
        'this': this,
        'caller': caller,
        # Who this verb runs *as*.  A verb acts with its programmer's
        # permissions rather than those of whoever typed the command,
        # which is what stops a player reaching everything a staff verb
        # can reach simply by invoking it.  The outermost frame is pushed
        # from the baton -- on the thread the verb runs on -- and reads
        # this to record the owner; nested calls get theirs from
        # call_verb.  Underscored because it is plumbing, not API.
        '_verb_owner': getattr(verb_def, 'owner', None),
        'location': location,
        'db': db,
        'verb': verb_name,
        'args': args,
        'argstr': argstr,
        # MOO's `args` is a *list* of the arguments; this engine's is the
        # argument string.  Both are useful and they are not the same
        # thing, so they get different names -- and code ported from a MOO
        # is translated to say argv.
        #
        # Without this, a ported verb doing args[1] became args[0], which
        # is the first *character* of a string, or IndexError on an empty
        # one.  1,570 of Inferno's 3,336 verbs index their arguments, so
        # nearly half a ported world was broken at runtime while reporting
        # as translated clean.
        #
        # call_verb overwrites this with the real list when a verb is
        # called with arguments; for a command it is the words the player
        # typed, which is what MOO would have put there.
        'argv': (args.split() if isinstance(args, str) else list(args or [])),
        # Kept so the execution sites can run the rest of the lifecycle
        # (veto check, at_post_cmd) against the same instance that parsed.
        '_verb_inst': verb_inst,
        # --- Messaging defaults (always available, may be overridden) ---
        'sub': None,
        'dob': None,
        'iob': None,
        'uob': None,
        'exclude': None,
    })

    if context is not None:
        namespace['context'] = context

    # --- Caller-supplied overrides: last, so they beat every layer ---
    # Written eagerly, which is what keeps them winning: a name present in
    # the dict never reaches __missing__.
    if extra:
        dict.update(namespace, extra)

    # Expose the raw call-kwargs dict so a verb can introspect arbitrary
    # keyword args it was given, without having to dig through globals().
    # Used e.g. by msg/msg_room to forward &N raw-string slots to esub.
    namespace['kwargs'] = dict(extra) if extra else {}

    return namespace


# =============================================================================
# Public API -- verb lifecycle around the body
# =============================================================================

def verb_body_vetoed(namespace: Dict[str, Any]) -> bool:
    """
    Whether ``at_pre_cmd()`` asked for this command to be dropped.

    The hook ran during namespace construction (before ``parse()``);
    this reports its verdict to the execution site, which skips the
    verb body when it is ``True``.  Returning ``True`` to suppress the
    default behaviour is the same convention the hook system uses.

    Args:
        namespace: A namespace from :func:`build_verb_namespace`.

    Returns:
        bool: ``True`` if the verb body should not run.  A namespace
        with no verb-type instance (verb-type resolution failed, or no
        verb_def was supplied) is never vetoed -- a command should not
        vanish because its type could not be built.
    """
    inst = namespace.get('_verb_inst')
    return bool(getattr(inst, '_vetoed', False)) if inst is not None else False


def run_at_post_cmd(namespace: Dict[str, Any], result: Any = None,
                    error: Optional[BaseException] = None) -> None:
    """
    Run the verb type's ``at_post_cmd()`` hook after the body.

    Called from every verb execution site, including when the body
    raised or was vetoed -- "cleanup that always happens" is the only
    version of a post hook worth having.  The outcome is published on
    the instance first, so the documented zero-argument signature still
    holds and a hook that wants the outcome can read it:

    * ``self.result``  -- the verb's return value (``None`` if it raised
      or was vetoed)
    * ``self.error``   -- the exception, or ``None``
    * ``self.vetoed``  -- whether ``at_pre_cmd()`` suppressed the body

    Args:
        namespace: A namespace from :func:`build_verb_namespace`.
        result:    The verb body's return value, if it ran.
        error:     The exception the body raised, if any.

    Notes:
        Errors from the hook are logged and swallowed.  This runs on
        the way out -- often already on an error path -- and a raising
        cleanup hook must not replace the original failure with its
        own.
    """
    inst = namespace.get('_verb_inst')
    if inst is None:
        return
    hook = getattr(inst, 'at_post_cmd', None)
    if hook is None:
        return
    try:
        inst.result = result
        inst.error = error
        inst.vetoed = bool(getattr(inst, '_vetoed', False))
        hook()
    except Exception as e:
        import logging
        logging.getLogger('megamoo.verb_namespace').error(
            f"at_post_cmd failed on {type(inst).__name__}: {e}", exc_info=True)
