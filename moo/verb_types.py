"""
Verb Type Definitions for MegaMOO

This module defines the class hierarchy for verb types -- the reusable
command-parsing classes that verbs inherit from.  Every verb attached to
a MOO object is backed by a *verb type* that controls how the player's
input is parsed into structured parts (direct object, preposition,
indirect object, switches, etc.) before the verb's code body runs.

Class hierarchy
---------------

::

    BaseVerb              Minimal verb -- bring-your-own parser.
      +-- MasterVerb      Standard dobj / prep / iobj parsing (most verbs).

* **BaseVerb** provides the lifecycle hooks the engine calls
  (``at_pre_cmd``, ``parse``, ``at_post_cmd``) plus unused scaffolding
  kept for compatibility -- ``func``, command matching, serialisation
  (``to_dict`` / ``from_dict``) -- and a convenience ``msg()`` method.

* **MasterVerb** extends ``BaseVerb`` with full natural-language command
  parsing identical in spirit to LambdaMOO's ``this none/any/this``
  spec or Evennia's ``MuxCommand``.  After ``parse()``, attributes like
  ``dobj``, ``prep``, ``iobj``, ``switches``, ``lhs``/``rhs``, etc.
  are populated and harvested into the verb body's namespace.

Verb-type registry
------------------

All verb-type classes are registered in a global dict keyed by their
dotted module path (e.g. ``'moo.verb_types.MasterVerb'``).  This allows
verb definitions stored in the database to reference their parent class
by string, which is resolved back to the class at load time via
:func:`resolve_verb_type`.

Dynamic verb creation
---------------------

The :func:`define_verb` factory creates a new verb class at runtime
(e.g. from in-game ``@verb`` or hot-reload).  It accepts the same
parameters as a class definition and returns a new class that inherits
from the specified parent.

Defining a new verb (class-based)::

    class DrinkVerb(MasterVerb):
        key = 'drink'
        aliases = ['sip', 'quaff']
        min = 2                          # 'dr' fires it
        help_text = 'Drink from a container.'

        def func(self):
            if not self.dobj:
                self.pobj.msg('Drink what?')
                return
            self.pobj.msg(f'You drink from {self.dobj}.')

Dynamic creation (e.g. from in-game @verb)::

    DrinkVerb = define_verb(
        'drink',
        aliases = ['sip', 'quaff'],
        min     = 2,
        parent  = 'moo.verb_types.MasterVerb',
        func    = lambda self: self.pobj.msg(f'You drink from {self.dobj}.'),
    )

Copyright (c) 2026
License: MIT
"""

from __future__ import annotations

import importlib
import logging
import re
from typing import Any, Dict, List, Optional, Type

logger = logging.getLogger('megamoo.verb_types')


# =============================================================================
# Verb-Type Registry
# =============================================================================
#
# The registry maps dotted class paths (e.g. 'moo.verb_types.BaseVerb')
# to the actual class objects.  This lets verb definitions stored in the
# database reference their parent class by a portable string key.
# =============================================================================

_VERB_TYPE_REGISTRY: Dict[str, Type['BaseVerb']] = {}


def _type_path(cls: type) -> str:
    """
    Return the canonical dotted path ``module.ClassName`` for *cls*.

    This is used as the registry key and as the ``parent_type`` value
    stored in serialised verb definitions.

    Args:
        cls: Any Python class.

    Returns:
        Dotted path string, e.g. ``'moo.verb_types.MasterVerb'``.
    """
    return f'{cls.__module__}.{cls.__qualname__}'


def register_verb_type(cls: Type['BaseVerb']) -> Type['BaseVerb']:
    """
    Class decorator that registers *cls* in the verb-type registry.

    After decoration, ``cls.parent_type`` is set to the dotted path of
    the class so it can be serialised and reconstructed later.

    Args:
        cls: The verb-type class to register.

    Returns:
        The same class, unchanged (aside from ``parent_type``).

    Example::

        @register_verb_type
        class MyCustomVerb(BaseVerb):
            ...
    """
    path = _type_path(cls)
    _VERB_TYPE_REGISTRY[path] = cls
    cls.parent_type = path
    return cls


def resolve_verb_type(path: str) -> Type['BaseVerb']:
    """
    Resolve a dotted path string to a verb-type class.

    Checks the in-memory registry first for fast lookup.  If the class
    has not been registered yet, falls back to a dynamic import of the
    module and ``getattr`` for the class name.

    Args:
        path: Dotted path like ``'moo.verb_types.MasterVerb'``.

    Returns:
        The resolved verb-type class.

    Raises:
        ImportError: If the path cannot be resolved (bad module or
            missing attribute).

    Example::

        cls = resolve_verb_type('moo.verb_types.MasterVerb')
        inst = cls()  # new MasterVerb instance
    """
    cls = _VERB_TYPE_REGISTRY.get(path)
    if cls is not None:
        return cls

    # Fall back to dynamic import: split 'moo.verb_types.MasterVerb'
    # into module='moo.verb_types' and class_name='MasterVerb'
    module_path, _, class_name = path.rpartition('.')
    if not module_path:
        raise ImportError(f'Cannot resolve verb type: {path!r}')
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    _VERB_TYPE_REGISTRY[path] = cls
    return cls


# =============================================================================
# BaseVerb -- Minimal Verb Base Class
# =============================================================================

@register_verb_type
class BaseVerb:
    """
    Minimal verb definition -- the root of the verb-type hierarchy.

    Subclass this only when you need completely custom parsing logic.
    Most verbs should inherit from :class:`MasterVerb` instead, which
    provides standard dobj/prep/iobj parsing out of the box.

    Class attributes (set when defining the verb class):

    ===============  ======================================================
    Attribute        Description
    ===============  ======================================================
    ``key``          Primary verb name (e.g. ``'look'``, ``'@create'``).
    ``aliases``      Alternative names (e.g. ``['l']``).
    ``min``          Minimum characters of *key* needed to match.  ``0``
                     means the full key is required.
    ``rexp``         Compiled regex applied to the argument string, or
                     ``None``.  Used by :meth:`parse` in subclasses.
    ``parent_type``  Dotted path of this class (set automatically by
                     :func:`register_verb_type`).
    ``help_text``    One-line help string shown by the help system.
    ``perms``        Permission string (default ``'rx'``).
    ===============  ======================================================

    Instance attributes (set at runtime before :meth:`parse`):

    ===============  ======================================================
    Attribute        Description
    ===============  ======================================================
    ``pobj``         Player object executing the verb.
    ``this``         The MOO object the verb is defined on.
    ``location``     ``pobj.location`` (MOOObject or ``None``).
    ``db``           Database reference.
    ``cmdstring``    The command string the player actually typed.
    ``raw``          Everything after the command string (unstripped).
    ``args``         ``raw.strip()`` -- the cleaned argument string.
    ===============  ======================================================

    Lifecycle
    ---------

    The engine calls these in order, around every verb execution --
    player commands, ``call_verb`` chains, and engine-invoked hooks
    alike::

        verb.at_pre_cmd()   # setup; return True to veto the command
        verb.parse()        # parse self.args into structured parts
        <the verb's .py body>
        verb.at_post_cmd()  # cleanup; always runs

    ``func()`` is **not** part of that sequence and is never called: a
    verb's body is the code stored on its ``VerbDef``, not a method
    here.  It survives only so that existing subclasses do not break.
    """

    # --- class-level defaults ---
    key: str = ''
    aliases: List[str] = []
    min: int = 0
    rexp: Optional[re.Pattern] = None
    parent_type: str = ''          # filled by register_verb_type
    help_text: str = ''
    perms: str = 'rx'

    def __init__(self):
        """
        Initialise runtime context slots.

        These are populated by the verb handler (server.py or
        VerbExecutor) *before* ``parse()`` is called.  They are set to
        safe defaults here so that introspection and ``to_dict()`` work
        even on freshly-constructed instances.
        """
        # Runtime context -- set by the verb handler before parse()
        self.pobj = None
        self.this = None
        self.location = None
        self.db = None
        self.cmdstring: str = ''
        self.raw: str = ''
        self.args: str = ''

    # -----------------------------------------------------------------
    # Matching
    # -----------------------------------------------------------------

    # Characters that act as verb prefixes -- the prefix character must
    # match between the player's input and the verb's key/alias.
    # For example, '@cre' matches '@create' but not 'create'.
    _VERB_PREFIXES = '@+'

    @classmethod
    def matches(cls, cmdstring: str) -> bool:
        """
        Return ``True`` if *cmdstring* would invoke this verb.

        Checks the primary *key* first, then every alias, using
        :attr:`min` for prefix matching.  A ``min`` of ``0`` requires
        an exact (case-insensitive) match.

        The ``@`` and ``+`` prefix characters are handled transparently:
        ``@cre`` can match ``@create`` and ``+wh`` can match ``+who``
        when ``min`` allows it, but ``@cre`` will never match ``create``
        (prefix must agree).

        Args:
            cmdstring: The command word typed by the player.

        Returns:
            ``True`` if this verb should handle the command.

        Examples::

            # Given: key='@create', aliases=['@cre'], min=3
            BaseVerb.matches('@cre')    # True  (prefix match, 3 >= min)
            BaseVerb.matches('@create') # True  (exact match)
            BaseVerb.matches('create')  # False (prefix '@' missing)
        """
        low = cmdstring.casefold()

        def _split_prefix(s):
            """Split a leading @ or + prefix from the rest of the name."""
            if s and s[0] in cls._VERB_PREFIXES:
                return s[0], s[1:]
            return '', s

        input_prefix, bare_input = _split_prefix(low)

        for name in [cls.key] + cls.aliases:
            target = name.casefold()
            target_prefix, bare_target = _split_prefix(target)

            # Prefix character must agree (both '@', both '+', or both empty)
            if target_prefix != input_prefix:
                continue

            if cls.min > 0:
                # Prefix matching: input must be at least `min` chars
                # and the target must start with the input
                if (len(bare_input) >= cls.min
                        and bare_target.startswith(bare_input)):
                    return True
            else:
                # Exact match required when min == 0
                if low == target:
                    return True

        return False

    # -----------------------------------------------------------------
    # Lifecycle hooks
    # -----------------------------------------------------------------

    def at_pre_cmd(self):
        """
        Called before :meth:`parse`, on every execution of this verb.

        Override for setup, or for a check that should abort before the
        cost of parsing -- which is also why the parsed slots
        (``dobj``, ``prep``, ``iobj``) are not populated yet.  Use
        :meth:`parse` or the verb body for anything that needs them.

        Returns:
            Returning ``True`` **vetoes the command**: the verb body is
            skipped entirely, as with the hook system's convention for
            suppressing a default.  Any other value (including
            ``None``) lets it run.

        Notes:
            An exception here is logged and the command proceeds.  One
            broken hook on a shared verb type must not silently swallow
            every command that uses it.
        """

    def parse(self):
        """
        Called after :meth:`at_pre_cmd`, before the verb body runs.

        The default implementation does nothing -- ``self.args`` is
        already available as a plain string.  Override in subclasses
        for custom argument parsing (or use :class:`MasterVerb` for
        standard dobj/prep/iobj parsing).
        """

    def func(self):
        """
        Dead scaffolding -- **the engine never calls this**.

        A verb's logic lives in its own ``.py`` file, executed as the
        verb body; there is no method here to override.  Kept only so
        that subclasses defining it keep importing.  For behaviour
        around the body use :meth:`at_pre_cmd` / :meth:`at_post_cmd`.
        """

    def at_post_cmd(self):
        """
        Called after the verb body, on every execution of this verb.

        Override for cleanup, logging, or side effects that should
        follow the verb.  It runs whatever happened -- including when
        the body raised, or never ran because :meth:`at_pre_cmd` vetoed
        it -- so cleanup here can be relied on.  The outcome is
        published on the instance first:

        * ``self.result``  -- the body's return value, or ``None``
        * ``self.error``   -- the exception it raised, or ``None``
        * ``self.vetoed``  -- whether :meth:`at_pre_cmd` suppressed it

        Notes:
            An exception here is logged and swallowed: this often runs
            on an error path, and a raising cleanup hook must not
            replace the failure it was reacting to.
        """

    # -----------------------------------------------------------------
    # Convenience
    # -----------------------------------------------------------------

    def msg(self, text: str):
        """
        Send *text* to the player who invoked this verb.

        This is a shortcut for ``notify(self.pobj, text)`` that handles
        the case where ``pobj`` might not be set (e.g. during testing).

        Args:
            text: Message string to send to the player.
        """
        if self.pobj and hasattr(self.pobj, 'objnum'):
            from .builtins import notify
            notify(self.pobj, text)

    # -----------------------------------------------------------------
    # Serialisation
    # -----------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialise this verb's class-level configuration to a dict.

        The returned dict is suitable for JSON storage in the database.
        It does **not** include runtime state (pobj, args, etc.) -- only
        the class definition metadata needed by :meth:`from_dict`.

        Returns:
            Dict with keys: ``key``, ``aliases``, ``min``,
            ``parent_type``, ``perms``, ``help_text``.
        """
        return {
            'key': self.key,
            'aliases': list(self.aliases),
            'min': self.min,
            'parent_type': self.parent_type or _type_path(type(self)),
            'perms': self.perms,
            'help_text': self.help_text,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BaseVerb':
        """
        Reconstruct a verb instance from a serialised dict.

        The ``parent_type`` field in *data* determines which class to
        instantiate.  If it points to a class other than ``cls``,
        :func:`resolve_verb_type` is used to look it up.

        Args:
            data: Dict as returned by :meth:`to_dict`.

        Returns:
            A new verb instance of the appropriate class, with
            class-level attributes populated from *data*.
        """
        parent_path = data.get('parent_type', _type_path(cls))
        verb_cls = resolve_verb_type(parent_path)
        inst = verb_cls()
        inst.key = data.get('key', '')
        inst.aliases = data.get('aliases', [])
        inst.min = data.get('min', 0)
        inst.perms = data.get('perms', 'rx')
        inst.help_text = data.get('help_text', '')
        return inst

    # -----------------------------------------------------------------
    # Repr
    # -----------------------------------------------------------------

    def __repr__(self):
        aliases = f' ({", ".join(self.aliases)})' if self.aliases else ''
        return f'<{type(self).__name__} {self.key!r}{aliases}>'


# =============================================================================
# MasterVerb -- Standard dobj / prep / iobj Parsing
# =============================================================================

@register_verb_type
class MasterVerb(BaseVerb):
    """
    Standard verb with full direct-object / preposition / indirect-object
    parsing.

    This is the verb type that most game verbs should inherit from.  The
    :meth:`parse` method splits the player's argument string on the
    first recognised preposition and populates a rich set of parsed
    attributes that are available inside :meth:`func`.

    Parsed attributes (available after ``parse()``)
    ------------------------------------------------

    ==============  ======================================================
    Attribute       Description
    ==============  ======================================================
    ``verb``        The verb string (same as ``cmdstring``).
    ``switches``    MUSH-style switches extracted from ``verb/sw1/sw2``.
    ``dobj``        Direct-object string (text before the preposition).
    ``dobjlist``    ``dobj`` split into words.
    ``prep``        First preposition found (canonical form, stripped).
    ``preplist``    ``prep`` split into words.
    ``iobj``        Indirect-object string (text after the preposition).
    ``iobjlist``    ``iobj`` split into words.
    ``prep2``       Second preposition (if any).
    ``dobj2``       Text after the second preposition.
    ``dobjlist2``   ``dobj2`` split into words.
    ``lhs``         Everything to the left of the first preposition.
    ``rhs``         Everything to the right of the first preposition.
    ``arglist``     ``args`` split into words.
    ``match``       The regex match object (or ``None``).
    ==============  ======================================================

    Parsing examples
    ----------------

    ::

        Input                         dobj          prep       iobj
        ----------------------------  ------------  ---------  ----------
        ''                            ''            ''         ''
        'sword'                       'sword'       ''         ''
        'blue sword from chest'       'blue sword'  'from'     'chest'
        'under old chest'             'old chest'   'under'    ''
        'ball from under old bed'     'ball'        'from under' 'old bed'
        '#10 = Rusty Sword'           '#10'         '='        'Rusty Sword'

    Switch parsing (MUSH-style)
    ---------------------------

    If the verb name contains ``/`` characters, they are split into
    switches::

        @create/quiet sword   ->  verb='@create', switches=['quiet']
        look/brief north      ->  verb='look',    switches=['brief']
    """

    def parse(self):
        """
        Parse ``self.args`` into structured dobj/prep/iobj components.

        This method is called automatically by the verb handler after
        runtime context (``pobj``, ``args``, etc.) is set.  It populates
        all the parsed attributes listed in the class docstring.

        The parsing strategy is:

        1. Extract MUSH-style switches from the verb name (``verb/sw``).
        2. Try special (single-character) prepositions first: ``=``,
           ``:``, ``?``, ``.`` -- these don't require surrounding spaces.
        3. If no special prep is found, search for a regular preposition
           using the global ``PREP_REGEX`` (or the verb's custom
           ``rexp`` if set).
        4. Split the argument string around the preposition into
           dobj (before) and iobj (after).
        5. Optionally detect a second preposition in the iobj portion.
        """
        from .globals import PREP_REGEX, SPECIAL_PREP_REGEX

        # Use verb-specific regex if set, else standard preps
        prep_re = self.rexp if self.rexp is not None else PREP_REGEX

        args = self.args
        verb = self.cmdstring or ''

        # --- Step 1: Extract MUSH-style switches (verb/sw1/sw2) ---
        if '/' in verb and verb != '/':
            parts = verb.split('/')
            verb = parts[0]
            self.switches = [s for s in parts[1:] if s]
        else:
            # Use injected switches (from call_verb) if available
            self.switches = getattr(self, '_injected_switches', []) or []

        dobj = ''
        prep = ''
        iobj = ''
        dobj2 = ''
        prep2 = ''
        lhs = ''
        rhs = ''

        # --- Step 2: Try special preps first (= : ? .) -- no spaces needed ---
        sp_match = SPECIAL_PREP_REGEX.search(args)
        if sp_match:
            prep = sp_match.group().strip()
            dobj = args[:sp_match.start()].strip()
            iobj = args[sp_match.end():].strip()
            lhs = dobj
            rhs = iobj
        else:
            # --- Step 3: Regular preposition search ---
            match = prep_re.search(args) if prep_re else None
            self.match = match

            if not match:
                # No preposition found -- entire args is the direct object
                dobj = args
            else:
                start = match.start()
                end = match.end()
                prep = match.group()

                if start == 0:
                    # Preposition is the first word: "under rock"
                    # In this case, the "dobj" is what follows the prep
                    dobj = args[end:]
                    rhs = dobj
                elif verb and verb[0] == '/':
                    # Slash shortcut: /emote -> verb='/', dobj = rest
                    verb = '/'
                    dobj = f'{self.cmdstring[1:]} {args}'.strip()
                else:
                    # Normal case: "sword from chest"
                    # dobj = text before prep, iobj = text after prep
                    dobj, iobj = args.split(prep, 1)
                    lhs = dobj
                    rhs = iobj

                    # --- Step 5: Check for a second preposition in iobj ---
                    match2 = prep_re.search(iobj) if prep_re else None
                    if match2:
                        dobj2 = iobj[match2.end():]
                        iobj = iobj[:match2.start()]
                        prep2 = match2.group()

        # --- Store everything, stripped of extraneous whitespace ---
        self.verb = verb.strip()
        self.dobj = dobj.strip()
        self.prep = prep.strip()
        self.iobj = iobj.strip()
        self.dobj2 = dobj2.strip()
        self.prep2 = prep2.strip()
        self.lhs = lhs.strip()
        self.rhs = rhs.strip()

        # Build word-split lists for each component
        self.arglist = args.split() if args else []
        self.dobjlist = self.dobj.split() if self.dobj else []
        self.preplist = self.prep.split() if self.prep else []
        self.iobjlist = self.iobj.split() if self.iobj else []
        self.dobjlist2 = self.dobj2.split() if self.dobj2 else []

    # MasterVerb initialises all parse-result slots in __init__ so they
    # always exist even if someone calls func() without parse().

    def __init__(self):
        """
        Initialise all parse-result attributes to safe defaults.

        This ensures that verb code can safely reference ``self.dobj``,
        ``self.prep``, etc. even if ``parse()`` has not been called
        (e.g. during testing or direct instantiation).
        """
        super().__init__()
        self.verb = ''
        self.switches: List[str] = []
        self.dobj = ''
        self.dobjlist: List[str] = []
        self.prep = ''
        self.preplist: List[str] = []
        self.iobj = ''
        self.iobjlist: List[str] = []
        self.dobj2 = ''
        self.dobjlist2: List[str] = []
        self.prep2 = ''
        self.lhs = ''
        self.rhs = ''
        self.arglist: List[str] = []
        self.match = None


# =============================================================================
# Dynamic Verb Creation
# =============================================================================

def define_verb(key: str, *,
                parent: str = 'moo.verb_types.MasterVerb',
                aliases: Optional[List[str]] = None,
                min: int = 0,
                rexp: Optional[re.Pattern] = None,
                perms: str = 'rx',
                help_text: str = '',
                parse: Any = None,
                func: Any = None,
                **extra) -> Type[BaseVerb]:
    """
    Create a new verb class dynamically at runtime.

    This factory is used by the in-game ``@verb`` command and by
    hot-reload to create verb classes without writing Python source
    files.  The returned class inherits from the specified *parent*
    and can be attached to any MOO object.

    Args:
        key:        Primary verb name (e.g. ``'look'``, ``'@create'``).
        parent:     Dotted path to the parent verb class (default:
                    ``'moo.verb_types.MasterVerb'``).  Resolved via
                    :func:`resolve_verb_type`.
        aliases:    Alternative names for the verb.
        min:        Minimum characters of *key* needed to match.
                    ``0`` means the full key is required.
        rexp:       Compiled regex for custom argument parsing.  If
                    provided, it replaces ``PREP_REGEX`` in
                    ``MasterVerb.parse()``.
        perms:      Permission string (default ``'rx'``).
        help_text:  One-line help description.
        parse:      Optional custom parse function ``(self) -> None``
                    that replaces the parent's ``parse()`` method.
        func:       Optional execution function ``(self) -> None``
                    that becomes the verb's ``func()`` method.
        **extra:    Any additional class attributes to set on the new
                    verb class.

    Returns:
        A new verb class that inherits from the resolved *parent*.
        The class name is auto-generated from *key* (e.g. ``'look'``
        becomes ``'LookVerb'``, ``'@create'`` becomes ``'CreateVerb'``).

    Example::

        LookVerb = define_verb(
            'look',
            aliases=['l'],
            min=1,
            func=lambda self: self.pobj.msg(f'You see {self.location.name}.'),
        )
    """
    parent_cls = resolve_verb_type(parent)

    attrs: Dict[str, Any] = {
        'key': key,
        'aliases': aliases or [],
        'min': min,
        'perms': perms,
        'help_text': help_text,
        **extra,
    }

    if rexp is not None:
        attrs['rexp'] = rexp
    if parse is not None:
        attrs['parse'] = parse
    if func is not None:
        attrs['func'] = func

    # Build a PascalCase class name: 'look' -> 'LookVerb', '@create' -> 'CreateVerb'
    class_name = key.lstrip('@+').replace(' ', '_').title() + 'Verb'

    verb_cls = type(class_name, (parent_cls,), attrs)
    verb_cls.parent_type = parent
    return verb_cls
