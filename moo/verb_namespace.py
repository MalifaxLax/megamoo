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

        # Native attrs (objnum, noun, flags, etc.) and special names
        # (contents, location, parent) are handled by __setattr__
        # and don't go through the property system — allow them for
        # the object's owner or wizards.
        if name in MOOObject._NATIVE_ATTRS or name in ('contents', 'location', 'parent'):
            if is_wizard or obj.owner == pobj_num:
                return setattr(obj, name, value)
            raise PermissionError(
                f"Permission denied: cannot set '{name}' on #{obj.objnum}"
            )

        # Check write permission on existing property
        try:
            prop_info = obj.get_property_info(name, db)
            if not prop_info.can_write(pobj_num, is_wizard):
                raise PermissionError(
                    f"Permission denied: cannot write '{name}' on #{obj.objnum}"
                )
        except KeyError:
            # Property doesn't exist — creating a new property.
            # Only allow if player is wizard or owns the object.
            if not is_wizard and obj.owner != pobj_num:
                raise PermissionError(
                    f"Permission denied: cannot create '{name}' on #{obj.objnum}"
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

    # Cached template of all public MOO builtins (avoids rebuilding
    # the dict on every verb execution)
    namespace.update(moo_builtins._get_builtin_ns_template())

    # Verb-calling-verb support: call_verb(obj, 'verb_name', ...)
    namespace['call_verb'] = moo_builtins.make_call_verb(pobj, db)

    # search() and find() bound to this database instance
    namespace['search'] = lambda *a, _db=db, **kw: moo_builtins._search_fn(*a, db=_db, **kw)
    namespace['find'] = lambda *a, _db=db, **kw: moo_builtins._find_fn(*a, db=_db, **kw)

    # String utilities (su.wrap, su.center, su.table, etc.)
    #
    # Bound under both names: `su` is the MegaMOO spelling, `string_utils`
    # is what code ported from a MOO already says, so `$string_utils`
    # resolves without an object behind it. Same instance either way.
    from .string_utils import su
    namespace['su'] = su
    namespace['string_utils'] = su

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
    # Inferno-style file builtins, confined to one directory.  Bound
    # unconditionally: they are present but refuse to work until a files
    # root is set, so a ported verb gets a clear error rather than a
    # NameError, and a server that never configured one is not exposed.
    from . import moo_files as _mf
    for _n in _mf.__all__:
        namespace[_n] = getattr(_mf, _n)

    from . import moo_builtins as _mb
    for _n in _mb.__all__:
        namespace[_n] = getattr(_mb, _n)

    # Effects utility (screen effects, delays, etc.)
    from .effects import eu as _effects_mgr
    namespace['_effects'] = _effects_mgr


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

    The namespace is built in layers (later layers can override earlier):

    1. Safe Python builtins (``len``, ``str``, ``range``, etc.)
    2. Core context variables (``pobj``, ``this``, ``db``, etc.)
    3. Parsed command parts (``dobj``, ``prep``, ``iobj``, etc.)
    4. Messaging defaults (``sub``, ``dob``, ``iob``, ``uob``, ``exclude``)
    5. MOO builtins and utilities (``notify``, ``call_verb``, ``su``, etc.)
    6. Depth-aware ``call_verb`` override (for nested verb chains)
    7. Globals module reference
    8. Extra caller-supplied overrides (kwargs from ``call_verb``, etc.)

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
    dict
        Namespace dict ready for ``exec(compiled_code, namespace)``.
    """
    if location is None:
        location = pobj.location

    # --- Layer 1: Safe Python builtins ---
    namespace: Dict[str, Any] = dict(SAFE_PYTHON_BUILTINS)

    # --- Layer 2: Core context variables ---
    namespace.update({
        'pobj': pobj,
        'player': pobj,
        'this': this,
        'caller': caller,
        'location': location,
        'db': db,
        'verb': verb_name,
        'args': args,
        'argstr': argstr,
    })

    if context is not None:
        namespace['context'] = context

    # --- Layer 2b: Permission-checking getattr/setattr ---
    namespace['getattr'] = _make_safe_getattr(pobj, db)
    namespace['setattr'] = _make_safe_setattr(pobj, db)
    # hasattr checks existence only (no permission enforcement) — knowing a
    # property exists is not the same as reading its value.
    namespace['hasattr'] = hasattr

    # --- Layer 3: Parsed command parts (from verb-type instance or fallback) ---
    verb_inst = None
    if verb_def is not None:
        verb_inst = _instantiate_verb_type(
            verb_def, pobj, this, location, db, verb_name, argstr,
            injected_switches=injected_switches,
        )

    # Kept so the execution sites can run the rest of the lifecycle
    # (veto check, at_post_cmd) against the same instance that parsed.
    namespace['_verb_inst'] = verb_inst

    if verb_inst is not None:
        # Verb-type parse succeeded -- use its structured results
        _parse_verb_inst_into_namespace(verb_inst, namespace)
    else:
        # Verb-type parse failed or no verb_def -- use simple fallbacks
        fallback_dobjstr = ''
        fallback_prep = ''
        fallback_iobjstr = ''
        fallback_switches: Optional[list] = None
        if parse_result is not None:
            fallback_dobjstr = getattr(parse_result, 'dobjstr', '') or ''
            fallback_prep = (getattr(parse_result, 'prep', '')
                             or getattr(parse_result, 'prepstr', '')
                             or '')
            fallback_iobjstr = getattr(parse_result, 'iobjstr', '') or ''
            fallback_switches = getattr(parse_result, 'switches', None)
        _set_parse_fallbacks(
            namespace,
            dobjstr=fallback_dobjstr,
            prep=fallback_prep,
            iobjstr=fallback_iobjstr,
            args=args,
            switches=fallback_switches,
        )

    # --- Layer 4: Messaging defaults (always available, may be overridden) ---
    namespace['sub'] = None
    namespace['dob'] = None
    namespace['iob'] = None
    namespace['uob'] = None
    namespace['exclude'] = None

    # --- Layer 5: MOO builtins, search/find, su, eu ---
    _inject_moo_builtins(namespace, pobj, db)

    # --- Layer 6: Override call_verb with depth-aware version when nested ---
    if call_depth > 0:
        from . import builtins as moo_builtins
        namespace['call_verb'] = moo_builtins.make_call_verb(pobj, db, call_depth)

    # --- Layer 6b: MOO compatibility (tell, pass_, E_* error values) ---
    # Must follow Layer 6: pass_ closes over whichever call_verb ended up in
    # the namespace, so a passed call keeps the same depth accounting.
    from .moo_compat import build_compat_namespace
    namespace.update(build_compat_namespace(
        this=this,
        verb_name=verb_name,
        call_verb=namespace.get('call_verb'),
        db=db,
    ))

    # --- Layer 7: Globals module (available in all verb namespaces) ---
    try:
        namespace['globals'] = __import__('moo.globals', fromlist=['globals'])
    except Exception:
        pass

    # --- Layer 8: Extra caller-supplied overrides (must come last) ---
    if extra:
        namespace.update(extra)

    # Expose the raw call-kwargs dict so a verb can introspect arbitrary
    # keyword args it was given, without having to dig through globals().
    # Used e.g. by msg/msg_room to forward %sN raw-string slots to esub.
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
