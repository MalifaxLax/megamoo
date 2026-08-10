"""
MegaMOO Hook / Event System

This module implements a hook-point registry that enables object lifecycle
events -- such as movement, creation, deletion, connection, and puppeting --
to be intercepted and handled by in-game verb code.

Overview
--------
A **hook point** is a named event (e.g. ``"before_move"``, ``"after_enter"``)
that the engine fires at specific moments during its internal operations. Each
hook point is associated with an ordered list of **verb aliases** -- when the
hook fires on a particular MOO object, the system tries each alias in order
and calls the first one that exists on the object. Only one verb fires per
hook point per object, preventing double-handling.

This design follows the Evennia/LambdaMOO convention of ``at_*`` verb names,
but allows multiple aliases so that builders can use whichever naming style
they prefer (e.g. ``at_before_move`` or ``at_pre_move``).

Before-Hooks vs After-Hooks
----------------------------
Hook points are classified as either **cancellable** or **informational**:

- **Before-hooks** (``cancellable=True``): Fired *before* the engine performs
  an action (e.g. before moving an object). If the hook verb returns
  ``False``, the action is cancelled entirely. This lets in-game code
  implement locks, guards, weight limits, etc.

- **After-hooks** (``cancellable=False``): Fired *after* the action has
  already been performed. The return value is ignored. These are used for
  notifications, room descriptions, stat updates, etc.

Architecture
------------
::

    Engine operation (e.g. move_object)
        |
        v
    fire_hook('before_move', mover_obj, args_str)
        |
        +--> _registry['before_move'].aliases = ['at_before_move', 'at_pre_move']
        |        |
        |        +--> obj.find_verb('at_before_move') -- found? call it, done.
        |        +--> obj.find_verb('at_pre_move')    -- fallback if first missing.
        |
        +--> returns verb result (False = cancel) or None (no verb found)
        |
        v
    Engine checks result; if False, aborts the move.

The hook verbs themselves are ordinary MOO verbs defined on game objects.
They are called via ``_call_hook()`` from ``builtins.py``, which sets up
the correct verb execution context (player, permissions, call depth).

Registration
------------
Hook points are registered at module load time at the bottom of this file.
Game code can also register custom hook points at runtime via
``register_hook()``.

Usage from verb code::

    # Fire an existing hook
    fire_hook('after_enter', room, str(player.objnum))

    # Register a new hook point for custom verbs
    register_hook('before_say', ['at_before_say'], cancellable=True,
                  description='Called on speaker before say')

See Also
--------
- ``builtins.py`` -- provides ``_call_hook()`` which performs the actual
  verb invocation, and re-exports ``fire_hook``, ``register_hook``, etc.
  into verb namespaces.
- ``verb_context.py`` -- the ContextVar carrying (pobj, db, depth) used
  by ``fire_hook()`` to access the current database.
- ``objects.py`` -- ``MOOObject.find_verb()`` resolves verb names through
  the inheritance chain.
"""

# =============================================================================
# IMPORTS
# =============================================================================

import logging
from typing import Any, List, NamedTuple

logger = logging.getLogger("megamoo.hooks")


# =============================================================================
# HOOK POINT DATA STRUCTURE
# =============================================================================


class HookPoint(NamedTuple):
    """
    Definition of a single hook point in the system.

    A HookPoint binds a logical event name to the list of verb aliases
    that should be tried (in order) on the target object, along with
    metadata about whether the hook can cancel the action.

    Attributes:
        name (str): Unique identifier for this hook point
            (e.g. ``'before_move'``, ``'after_enter'``).
        aliases (List[str]): Ordered list of verb names to try on the
            target object. The first alias found on the object is
            called; no others are tried. This allows builders to use
            whichever naming convention they prefer.
        cancellable (bool): If ``True``, this is a "before-hook" and
            the hook verb may return ``False`` to cancel the engine
            action. If ``False``, this is an "after-hook" and the
            return value is ignored.
        description (str): Human-readable explanation of when and why
            this hook fires. Used by ``@hooks`` and documentation.
    """

    name: str
    aliases: List[str]
    cancellable: bool
    description: str = ""


# =============================================================================
# HOOK REGISTRY -- maps hook point names to HookPoint definitions
# =============================================================================

# The registry is a module-level dict populated at import time (see bottom
# of file) and optionally extended by game code via register_hook().
_registry: dict[str, HookPoint] = {}


# =============================================================================
# PUBLIC API
# =============================================================================


def register_hook(
    name: str,
    aliases: List[str],
    cancellable: bool = False,
    description: str = "",
) -> None:
    """
    Register a new hook point in the system.

    Each hook point must have a unique name. Once registered, the hook
    can be fired with ``fire_hook()`` and will try the specified verb
    aliases on the target object.

    This is called at module load time to set up the default hooks
    (movement, lifecycle, connection, etc.), but can also be called
    from game startup code or verbs to register custom hook points.

    Args:
        name: Unique hook point name (e.g. ``'before_move'``). Must
            not already be registered.
        aliases: Ordered list of verb names to try on the target
            object when this hook fires. The first match wins; only
            one verb is called per hook invocation. Example:
            ``['at_before_move', 'at_pre_move']``.
        cancellable: Whether the hook verb can cancel the engine
            action by returning ``False``. Set to ``True`` for
            before-hooks and ``False`` for after-hooks.
        description: Human-readable description of the hook point's
            purpose. Shown by introspection commands like ``@hooks``.

    Raises:
        ValueError: If a hook point with the given *name* is already
            registered.
    """
    if name in _registry:
        raise ValueError(f"Hook point '{name}' is already registered")
    _registry[name] = HookPoint(
        name=name,
        aliases=list(aliases),
        cancellable=cancellable,
        description=description,
    )


def fire_hook(hook_point: str, obj, args_str: str = "") -> Any:
    """
    Fire a registered hook point on a MOO object.

    Iterates through the hook point's alias list and calls the first
    verb found on the object. The verb is invoked via ``_call_hook()``
    from ``builtins.py``, which handles verb context setup, permission
    checks, and depth tracking.

    Only one verb fires per hook point per object -- the first alias
    that ``obj.find_verb()`` resolves successfully. If no alias is
    found, the hook is silently skipped (returns ``None``).

    For **cancellable** hooks (before-hooks), the caller should check
    the return value: if it is ``False``, the action should be
    cancelled.

    Args:
        hook_point: Name of the registered hook point to fire
            (e.g. ``'before_move'``, ``'after_enter'``).
        obj: The MOOObject to call the hook verb on. The verb is
            resolved via the object's inheritance chain.
        args_str: Argument string to pass to the hook verb. Typically
            contains the object number(s) involved in the action
            (e.g. ``str(player.objnum)``).

    Returns:
        The hook verb's ``result`` value if a verb was found and
        called, or ``None`` if:
        - No alias was found on the object.
        - No verb execution context is currently active.

    Raises:
        KeyError: If *hook_point* is not a registered hook point name.
    """
    hp = _registry.get(hook_point)
    if hp is None:
        raise KeyError(f"Unknown hook point: '{hook_point}'")

    # Access the current verb execution context (pobj, db, depth)
    from .verb_context import verb_ctx

    ctx = verb_ctx.get(None)
    if ctx is None:
        # No active verb context -- can happen during early server startup
        # or in non-verb code paths. Silently skip.
        return None
    _, db, _ = ctx

    # Late import to avoid circular dependency between hooks.py and builtins.py
    from .builtins import _call_hook

    # Try each alias in order; call the first one that exists on the object
    for alias in hp.aliases:
        try:
            defining_objnum, verb_def = obj.find_verb(alias, db)
        except Exception as exc:
            logger.error(f"Hook '{hook_point}' find_verb('{alias}') on #{obj.objnum} failed: {exc}")
            continue
        if verb_def is not None:
            # Found a matching verb -- call it and return the result.
            # No further aliases are tried.
            return _call_hook(obj, alias, args_str)

    # No alias was found on this object -- hook is a no-op
    return None


# =============================================================================
# QUERY HELPERS -- introspection for game code and debugging
# =============================================================================


def get_hook_aliases(hook_point: str) -> List[str]:
    """
    Return the alias list for a hook point.

    Useful for game code that wants to know which verb names are
    associated with a particular hook.

    Args:
        hook_point: Name of the registered hook point.

    Returns:
        List[str]: A copy of the alias list, or an empty list if
            the hook point is not registered.
    """
    hp = _registry.get(hook_point)
    return list(hp.aliases) if hp else []


def is_cancellable(hook_point: str) -> bool:
    """
    Check whether a hook point supports cancellation.

    Args:
        hook_point: Name of the registered hook point.

    Returns:
        bool: ``True`` if the hook is cancellable (a before-hook),
            ``False`` if it is informational (an after-hook) or if
            the hook point is not registered.
    """
    hp = _registry.get(hook_point)
    return hp.cancellable if hp else False


def list_hooks() -> dict:
    """
    Return a copy of the full hook registry for introspection.

    This powers the ``@hooks`` wizard command and can be used by
    game code to enumerate all registered hook points.

    Returns:
        dict: A dictionary mapping hook point names (str) to
            ``HookPoint`` named tuples.
    """
    return dict(_registry)


# =============================================================================
# DEFAULT HOOK REGISTRATIONS
# =============================================================================
# These hook points are registered at module import time and correspond
# to the core engine events. Game code can register additional custom
# hooks at runtime using register_hook().

# -----------------------------------------------------------------------------
# Movement hooks -- fired during object relocation (move_object / move_to)
# -----------------------------------------------------------------------------
# The movement sequence fires hooks in this order:
#   1. before_move  on the mover        (cancellable)
#   2. before_leave on the old location  (cancellable)
#   3. before_enter on the destination   (cancellable)
#   4. (engine performs the move)
#   5. after_move   on the mover
#   6. after_leave  on the old location
#   7. after_enter  on the destination

register_hook(
    "before_move",
    ["at_before_move", "at_pre_move"],
    cancellable=True,
    description="Called on mover before move; return False to cancel",
)
register_hook(
    "before_leave",
    ["at_before_leave"],
    cancellable=True,
    description="Called on old location before move; return False to cancel",
)
register_hook(
    "before_enter",
    ["at_before_enter"],
    cancellable=True,
    description="Called on destination before move; return False to cancel",
)
register_hook(
    "after_move",
    ["at_after_move", "at_post_move"],
    cancellable=False,
    description="Called on mover after move",
)
register_hook(
    "after_leave",
    ["at_after_leave", "exit_func"],
    cancellable=False,
    description="Called on old location after move",
)
register_hook(
    "after_enter",
    ["at_after_enter", "enter_func"],
    cancellable=False,
    description="Called on destination after move",
)

# -----------------------------------------------------------------------------
# Object lifecycle hooks -- fired during creation and deletion
# -----------------------------------------------------------------------------

register_hook(
    "object_creation",
    ["at_object_creation"],
    cancellable=False,
    description="Called on newly created object",
)
register_hook(
    "before_recycle",
    ["at_before_recycle"],
    cancellable=True,
    description="Called on object before recycling; return False to cancel",
)
register_hook(
    "object_delete",
    ["at_object_delete"],
    cancellable=False,
    description="Called on location when contained object is recycled",
)

# -----------------------------------------------------------------------------
# Reparent hooks -- fired when an object's parent changes
# -----------------------------------------------------------------------------

register_hook(
    "before_reparent",
    ["at_before_reparent", "at_pre_reparent"],
    cancellable=True,
    description="Called on object before reparenting; return False to cancel",
)
register_hook(
    "after_reparent",
    ["at_after_reparent", "at_post_reparent"],
    cancellable=False,
    description="Called on object after reparenting; args = old_parent_num",
)

# -----------------------------------------------------------------------------
# Connection hooks -- fired on player connect/disconnect
# -----------------------------------------------------------------------------

register_hook(
    "on_disconnect",
    ["at_disconnect", "on_disconnect"],
    cancellable=False,
    description="Called on player object when connection is lost",
)

# -----------------------------------------------------------------------------
# Puppet hooks -- fired when a player puppets/unpuppets a character
# -----------------------------------------------------------------------------
# "Puppeting" means a player takes control of a character object.
# on_puppet fires after the character has been moved to its last_location.
# on_unpuppet fires before the character is stored away in limbo (#2).

register_hook(
    "on_puppet",
    ["at_puppet", "on_puppet"],
    cancellable=False,
    description="Called on character after puppeting in (moved to last_location)",
)
register_hook(
    "on_unpuppet",
    ["at_unpuppet", "on_unpuppet"],
    cancellable=False,
    description="Called on character before being stored in #2 (unpuppet/disconnect)",
)
