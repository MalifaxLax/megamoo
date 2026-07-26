"""
Verb Execution Context for MegaMOO

This module provides a thread-safe, async-safe mechanism for tracking
the *active verb execution context* using Python's ``contextvars``
module.  It allows any code running inside a verb execution -- even
code that was not explicitly passed the player or database references
-- to discover the current execution context.

Why this is needed
------------------

When verb code runs, it may call methods on MOO objects (e.g.
``obj.name``, ``obj.move_to(...)``).  Those methods sometimes need to
know *who* is executing the verb (for permission checks) and *which
database* to use (for object lookups).  Rather than threading ``pobj``
and ``db`` through every method signature, the verb execution context
is stored in a ``ContextVar`` that can be read from anywhere in the
call stack.

This is similar to how web frameworks use request-local storage or
how asyncio tasks inherit context variables.

Usage pattern
-------------

The verb handler sets the context before executing verb code and
clears it afterwards using a try/finally block::

    from moo.verb_context import set_verb_context, clear_verb_context

    token = set_verb_context(pobj, db, depth=0)
    try:
        exec(compiled_code, namespace)
    finally:
        clear_verb_context(token)

Code that needs the context (e.g. ``MOOObject.__getattr__``) reads it::

    from moo.verb_context import verb_ctx

    ctx = verb_ctx.get(None)
    if ctx:
        pobj, db, depth = ctx
        # ... use pobj and db ...

Nesting support
---------------

The context variable supports nesting via tokens.  When
``set_verb_context()`` is called inside an already-active verb
execution (e.g. from ``call_verb``), it saves the previous context
and the token returned by ``set_verb_context()`` can restore it
when passed to ``clear_verb_context()``.  The *depth* parameter
tracks the current nesting level to enforce ``MAX_VERB_DEPTH``.

Copyright (c) 2026
License: MIT
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:
    from .objects import MOOObject
    from .database import Database


# =============================================================================
# Context Variable
# =============================================================================

# The context variable holds a tuple of (pobj, db, depth) or None.
#
#   pobj  -- the player object executing the verb (MOOObject)
#   db    -- the database instance (Database)
#   depth -- the current verb-calling-verb nesting depth (int)
#
# Default is None (no verb is currently executing).
verb_ctx: ContextVar[Optional[Tuple[MOOObject, Database, int]]] = ContextVar(
    'verb_ctx', default=None
)

# Maximum allowed verb-calling-verb nesting depth.
# Prevents infinite recursion from verbs that call each other.
MAX_VERB_DEPTH = 50


# =============================================================================
# Public API
# =============================================================================

def set_verb_context(pobj: MOOObject, db: Database, depth: int = 0) -> Token:
    """
    Set the active verb execution context.

    This should be called immediately before executing verb code.
    The returned token **must** be passed to :func:`clear_verb_context`
    in a ``finally`` block to restore the previous context.

    Args:
        pobj:  The player object executing the verb.
        db:    The database instance.
        depth: Current verb-calling-verb nesting depth (default ``0``
               for top-level commands; incremented by ``call_verb``).

    Returns:
        A ``contextvars.Token`` that must be passed to
        :func:`clear_verb_context` to restore the prior state.

    Example::

        token = set_verb_context(player, db, depth=0)
        try:
            exec(verb_code, namespace)
        finally:
            clear_verb_context(token)
    """
    return verb_ctx.set((pobj, db, depth))


def clear_verb_context(token: Token):
    """
    Restore the previous verb execution context.

    This undoes the effect of the corresponding :func:`set_verb_context`
    call, restoring whatever context was active before it (which may be
    ``None`` if this was the outermost verb, or a parent context if
    this is a nested ``call_verb``).

    Args:
        token: The token returned by the matching
               :func:`set_verb_context` call.
    """
    verb_ctx.reset(token)
