"""
MegaMOO Object System

This module implements the core MOO object model with hierarchical inheritance,
properties, and verbs. Every object in the MOO universe is an instance of MOOObject.

The object system follows LambdaMOO conventions:
    - Objects are numbered sequentially (#1, #2, #3, ...)
    - #1 is the root system object
    - Objects inherit properties and verbs from their parent
    - Children can override parent properties/verbs
    - Multiple inheritance is not supported (single parent only)

Architecture Overview:

    The object graph forms a single-parent tree rooted at object #1.  Each
    object stores its own *local* properties and verbs; inherited values are
    resolved at runtime by walking the parent chain.  To avoid repeated
    O(depth) walks, a **flattened inheritance cache** is built lazily and
    stored on each object.  The cache is invalidated whenever a property or
    verb changes anywhere in the ancestor chain, and the invalidation
    propagates to all descendants.

    Python attribute access (``obj.foo``) is overloaded via ``__getattr__``
    and ``__setattr__`` so that MOO properties and verbs can be read and
    written with natural syntax.  A small set of "native" attributes
    (``objnum``, ``noun``, ``flags``, etc.) bypass the MOO property layer
    and are stored directly on the Python instance.

    Objects are persisted to the database via ``to_dict()`` / ``from_dict()``
    and can optionally auto-save on every mutation when a database reference
    is attached.

Key Classes:
    ObjectFlags:   Bit-flag enum controlling player/wizard/permission states.
    PropertyInfo:  Dataclass holding a single property's value and metadata.
    TagHandler:    Evennia-style tag system stored as a hidden MOO property.
    MOOObject:     The core object class representing everything in the world.

Copyright (c) 2026
License: MIT
"""

# ---------------------------------------------------------------------------
# Standard library and third-party imports
# ---------------------------------------------------------------------------

from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import IntEnum
import asyncio
import logging
from contextlib import contextmanager
import time

logger = logging.getLogger('megamoo.objects')

# (objnum, name) pairs already reported as a property shadowing a verb.
# The inheritance cache is rebuilt whenever anything in an ancestor
# changes, and a world can hold tens of thousands of objects -- without
# this the same collision is announced on every rebuild, and a warning
# nobody can read is not a warning.  Cleared by clear_shadow_reports()
# so a builder who fixes one can be told if it comes back.
_reported_shadowed_verbs = set()


def clear_shadow_reports():
    """Forget which property/verb collisions have already been logged."""
    _reported_shadowed_verbs.clear()


# ===========================================================================
# OBJECT FLAGS
# ===========================================================================


class ObjectFlags(IntEnum):
    """
    Bit-flag constants governing object capabilities and permission levels.

    These flags are stored as a single integer bitmask on each MOOObject
    (``obj.flags``).  Multiple flags can be combined with bitwise OR and
    tested with ``has_flag()``.

    Attributes:
        PLAYER:    Marks the object as a connected or connectable player
                   character.  Player objects receive network messages via
                   ``notify()`` and are matched by ``is_player``.
        PROGRAMMER: Grants the ability to create and edit verb code.
                   Programmers can use ``@program``, ``eval``, etc.
        WIZARD:    Superuser flag -- bypasses all permission checks.
                   Wizards implicitly have PROGRAMMER rights as well.
        READABLE:  Allows any player to read this object's properties,
                   regardless of individual property permissions.
        WRITABLE:  Allows any player to write this object's properties,
                   regardless of individual property permissions.
        FERTILE:   Permits this object to be used as a parent when
                   creating new objects.  Non-fertile objects cannot be
                   inherited from (except by wizards).

    Notes:
        Flags are persisted as part of ``to_dict()`` and restored by
        ``from_dict()``.  The PLAYER flag may also be auto-set during
        deserialization for backward compatibility with older databases
        that stored a separate ``player`` field.
    """
    PLAYER = 1 << 0      # This object is a player
    PROGRAMMER = 1 << 1  # Can create/edit code
    WIZARD = 1 << 2      # Has full system access
    READABLE = 1 << 3    # Anyone can read properties
    WRITABLE = 1 << 4    # Anyone can write properties
    FERTILE = 1 << 5     # Can be used as parent for new objects


# ===========================================================================
# PROPERTY METADATA
# ===========================================================================


@dataclass
class PropertyInfo:
    """
    Property definition and metadata.

    Properties in MOO have both a value and associated metadata that controls
    inheritance, permissions, and ownership.  Each ``PropertyInfo`` is stored
    in the owning object's ``properties`` dict keyed by property name.

    When the inheritance cache is built, inherited properties (those with
    the ``'c'`` permission) are visible on descendant objects.  Children
    may create a *local override* by adding a same-named property to their
    own ``properties`` dict, which shadows the inherited value.

    Attributes:
        name (str): Property name (must match the dict key on the object).
        value (Any): Current property value.  Can be any Python type;
            MOOObject values are auto-converted to ``'#N'`` strings on
            storage and resolved back to live objects on read.
        owner (int): Object number of the player who owns this property.
            Ownership determines who can write when ``'w'`` is set.
        perms (str): Permission string composed of the following characters:
            ``'r'`` -- Readable by anyone (not just the owner).
            ``'w'`` -- Writable by the owner (non-owners can never write
                       unless they are wizards).
            ``'c'`` -- Inherited to children.  When absent, the property is
                       local-only and will not appear on descendants.

    Permission String Format:
        'r'  - Readable by anyone
        'w'  - Writable by owner
        'c'  - Inherited to children (clear means child gets its own copy)
    """
    name: str
    value: Any = None
    owner: int = 0
    perms: str = "rc"
    
    @property
    def is_readable(self) -> bool:
        """Check if property is readable by anyone."""
        return 'r' in self.perms
        
    @property
    def is_writable(self) -> bool:
        """Check if property is writable."""
        return 'w' in self.perms
        
    @property
    def is_inherited(self) -> bool:
        """Check if property is inherited to children."""
        return 'c' in self.perms
        
    def can_read(self, player_objnum: int, player_wizard: bool = False) -> bool:
        """
        Check if a player can read this property.
        
        Args:
            player_objnum: Player's object number
            player_wizard: Whether player is a wizard
            
        Returns:
            bool: True if player can read
        """
        if player_wizard:
            return True
        if self.is_readable:
            return True
        if player_objnum == self.owner:
            return True
        return False
        
    def can_write(self, player_objnum: int, player_wizard: bool = False) -> bool:
        """
        Check if a player can write this property.

        Mirrors :meth:`can_read`: the permission bit opens the property to
        everyone, and the owner never needed the bit in the first place.

        It used to read ``return self.is_writable`` for the owner, which
        inverted the MOO model -- there ``w`` is what grants write to
        *other* people, and an owner may always write their own property.
        The practical effect was that 2,043 of 2,045 properties in a real
        world refused their own owner, so nothing could use the checked
        path, so nothing was checked.

        Args:
            player_objnum: Player's object number
            player_wizard: Whether player is a wizard

        Returns:
            bool: True if player can write
        """
        if player_wizard:
            return True
        if self.is_writable:
            return True
        if player_objnum == self.owner:
            return True
        return False


# ===========================================================================
# NULL ATTRIBUTE SENTINEL
# ===========================================================================


class _NullAttr:
    """
    Sentinel object returned when a MOO property or verb lookup fails.

    ``_NullAttr`` is designed to be maximally forgiving: it is falsy,
    stringifies to the empty string, compares equal to ``None``, orders
    as zero, and can be called without raising (returns ``None``).  This
    lets verb code read a property that may not exist without guarding
    it::

        if pobj.rt > 0:            # rt need not be defined anywhere
            pobj.msg("You must wait.")

    Ordering treats a missing property as ``0``, which is what game code
    almost always means by it: no roundtime, no damage, no stack.  It is
    the same premise as being falsy, extended to ``<`` and ``>`` so that
    numeric properties do not each need an ``or 0``.  Comparison against
    a non-number returns ``NotImplemented`` and so still raises, because
    ``obj.name > 5`` is a real mistake rather than a missing value.

    A single module-level instance (``_null_attr``) is reused for all
    missing-property returns to avoid unnecessary allocations.

    Notes:
        ``__slots__`` is empty to keep the object tiny.  All behaviour
        is defined via dunder methods.
    """
    __slots__ = ()
    def __bool__(self): return False
    def __call__(self, *args, **kwargs): return None
    def __repr__(self): return 'None'
    def __str__(self): return ''
    def __eq__(self, other): return other is None or isinstance(other, _NullAttr)
    def __hash__(self): return hash(None)

    # Ordering: a missing numeric property behaves as 0.  bool is excluded
    # deliberately -- it is an int subclass, but `obj.flag > True` is not a
    # numeric comparison anyone means to make.
    def _as_zero(self, other):
        if isinstance(other, bool) or not isinstance(other, (int, float)):
            return NotImplemented
        return 0
    def __lt__(self, other):
        z = self._as_zero(other)
        return NotImplemented if z is NotImplemented else z < other
    def __le__(self, other):
        z = self._as_zero(other)
        return NotImplemented if z is NotImplemented else z <= other
    def __gt__(self, other):
        z = self._as_zero(other)
        return NotImplemented if z is NotImplemented else z > other
    def __ge__(self, other):
        z = self._as_zero(other)
        return NotImplemented if z is NotImplemented else z >= other

# Module-level singleton -- every missing-property lookup returns this
# same object rather than creating a new one each time.
_null_attr = _NullAttr()


# ===========================================================================
# TAG HANDLER
# ===========================================================================


class TagHandler:
    """
    Evennia-style tag handler attached to every MOOObject.

    Tags provide a lightweight categorisation mechanism that is stored as
    a hidden MOO property (``_tags``) on the object.  Each tag belongs to
    a *category* (defaulting to ``'general'``), and a category can hold
    any number of string tags.

    The internal storage format is a plain dict::

        {'general': ['foo', 'bar'], 'zone': ['overworld']}

    Because the data lives in a normal MOO property, it is automatically
    serialised and deserialised with the rest of the object, and
    participates in the auto-save mechanism.

    Attributes:
        _obj (MOOObject): The object this handler is attached to.

    Notes:
        The ``_tags`` property is prefixed with an underscore so it is
        invisible to normal MOO property enumeration and attribute
        access (``__getattr__`` skips names starting with ``_``).
    """

    def __init__(self, obj: 'MOOObject'):
        self._obj = obj

    def _get_tags(self) -> dict:
        """Return the raw tags dict from the hidden ``_tags`` property."""
        props = self._obj.__dict__.get('properties', {})
        if '_tags' in props:
            return props['_tags'].value or {}
        return {}

    def _set_tags(self, data: dict):
        """Write *data* back to the ``_tags`` property, creating it if needed."""
        props = self._obj.__dict__.get('properties', {})
        if '_tags' in props:
            props['_tags'].value = data
        else:
            self._obj.properties['_tags'] = PropertyInfo(
                name='_tags', value=data, owner=self._obj.owner, perms='rc'
            )
        # Invalidate caches so descendants see updated tags
        self._obj._invalidate_local()
        self._obj._auto_save_to_db()

    def all(self) -> dict:
        """
        Return all tags grouped by category.

        Returns:
            dict: Mapping of ``{category: [tag, ...]}`` (a shallow copy).
        """
        return dict(self._get_tags())

    def add(self, tag=None, category=None):
        """
        Add a tag to a category.

        Args:
            tag (str): Tag string to add.  If ``None``, the category is
                created as an empty list (useful for reserving a category).
            category (str): Category name.  Defaults to ``'general'``.

        Notes:
            Duplicate tags within the same category are silently ignored.
        """
        category = category or 'general'
        data = self._get_tags()
        if category not in data:
            data[category] = []
        if tag and tag not in data[category]:
            data[category].append(tag)
        self._set_tags(data)

    def remove(self, tag=None, category=None):
        """
        Remove a tag from a category, or remove an entire category.

        Args:
            tag (str): Tag to remove.  If ``None``, the entire *category*
                is deleted.
            category (str): Category to operate on.  Defaults to ``'general'``.

        Notes:
            If removing the last tag in a category, the category itself is
            also cleaned up to keep the storage dict tidy.
        """
        category = category or 'general'
        data = self._get_tags()
        if category not in data:
            return
        if tag:
            if tag in data[category]:
                data[category].remove(tag)
                # Auto-clean empty categories
                if not data[category]:
                    del data[category]
        else:
            del data[category]
        self._set_tags(data)

    def has(self, tag, category=None) -> bool:
        """
        Check whether a tag exists on this object.

        Args:
            tag (str): The tag string to look for.
            category (str): If given, restrict the search to this category.
                Otherwise searches all categories.

        Returns:
            bool: ``True`` if the tag is present.
        """
        data = self._get_tags()
        if category:
            return tag in data.get(category, [])
        # Search across every category
        return any(tag in tags for tags in data.values())

    def get(self, category) -> list:
        """
        Return all tags belonging to a single category.

        Args:
            category (str): Category to retrieve.

        Returns:
            list: List of tag strings (empty list if the category does
            not exist).
        """
        return list(self._get_tags().get(category, []))


# ===========================================================================
# CORE MOO OBJECT
# ===========================================================================


class MOOObject:
    """
    Base MOO object class -- the fundamental building block of the world.

    This class represents a single object in the MOO universe. Objects can be
    anything: rooms, things, players, exits, or abstract concepts.  The same
    class is used for all of them; behaviour differences come from which
    verbs and properties are defined (typically via inheritance from
    prototype objects like ``$room``, ``$thing``, ``$player``).

    Object Hierarchy:
        Every object (except #1, the root) has exactly one parent object.
        Properties and verbs are inherited from parent to child, with
        children able to override inherited values.  The inheritance tree
        is single-parent only (no diamond inheritance).

    Attribute Access Model:
        ``__getattr__`` and ``__setattr__`` are overloaded so that reading
        or writing an attribute whose name is *not* in ``_NATIVE_ATTRS``
        and does *not* start with ``_`` goes through the MOO property
        system.  This means verb code can use natural Python syntax::

            this.damage = 25          # creates/updates MOO property 'damage'
            amount = this.damage      # reads MOO property 'damage'
            this._title()             # calls verb '_title' on this object

    Attributes:
        objnum (int): Unique object number (e.g., 1, 2, 3).  By
            convention displayed with a ``#`` prefix (``#1``).
        parent (int): Object number of this object's parent in the
            inheritance tree.  ``0`` means no parent (root object).
        children (Set[int]): Object numbers of direct children.
        noun (str): The atomic/internal name of the object (e.g. "sword").
        name (str): Display name (read-only property -- returns the
            MOO property ``'name'`` if set, otherwise ``noun``).
        aliases (List[str]): Alternative names for matching in commands.
        owner (int): Object number of the player who owns this object.
        location (property): The object this is inside (returns MOOObject
            or ``None``).  Stored internally as ``_location_id``.
        contents (property): Objects inside this one (returns list of
            MOOObject).  Stored internally as ``_content_ids``.
        flags (int): Bitmask of ``ObjectFlags`` values.
        properties (Dict[str, PropertyInfo]): Locally-defined MOO
            properties.  Inherited properties live on ancestor objects.
        verbs (List[VerbDef]): Locally-defined verb definitions.
        created (float): Unix timestamp when the object was created.
        last_move (float): Unix timestamp of the most recent ``move_to``.
        tags (TagHandler): Evennia-style tag system for categorisation.
    """
    
    def __init__(self, objnum: int, parent: int = 0, owner: int = 0):
        """
        Initialize a MOO object.
        
        Args:
            objnum: Object number for this object
            parent: Parent object number (0 for root object)
            owner: Owner object number
        """
        # --- Core identity ---
        self.objnum = objnum
        self.parent = parent
        self.children: Set[int] = set()
        self.noun = f"Object #{objnum}"
        self.aliases: List[str] = []
        self.owner = owner

        # --- Spatial containment ---
        # Stored as raw ints; the ``location`` and ``contents`` property
        # descriptors resolve them to live MOOObject instances on read.
        self._location_id = 0
        self._content_ids: List[int] = []

        # --- Permissions & flags ---
        self.flags = 0

        # --- MOO data ---
        self.properties: Dict[str, PropertyInfo] = {}
        self.verbs: List = []  # Will be VerbDef objects from the verbs module

        # --- Timestamps ---
        self.created = time.time()
        self.last_move = self.created

        # --- Tag system (Evennia-style categorisation) ---
        self.tags = TagHandler(self)

        # --- Flattened inheritance cache ---
        # When valid, these hold the fully-resolved property/verb tables
        # so lookups are O(1) instead of O(parent-chain depth).
        # Each entry is a tuple of (PropertyInfo_or_VerbDef, defining_objnum)
        # so callers know where the value originated.
        self._resolved_properties: Optional[Dict[str, Tuple['PropertyInfo', int]]] = None
        self._resolved_verbs: Optional[Dict[str, Tuple[Any, int]]] = None
        self._inheritance_cache_valid = False

        # Legacy flag kept for compatibility with code that checks
        # ``obj._cache_dirty`` directly.
        self._cache_dirty = True

        # --- Auto-save configuration ---
        # When ``_auto_save`` is True and ``_database`` is set, every
        # mutation (property change, move, etc.) immediately persists
        # the object.  ``_pending_save`` tracks deferred saves when
        # auto-save is disabled (batch mode).
        self._auto_save = True
        self._database = None   # Assigned by the database layer on load
        self._pending_save = False

        # --- Write tracking ---
        #
        # Saving used to rewrite the whole object every time: DELETE all
        # properties, re-INSERT all of them, DELETE all verbs, re-INSERT
        # all of them *including full source text* -- 192 statements for
        # one property change on a character prototype.
        #
        # `_dirty_props` names the properties whose values changed, so a
        # save can touch only those.  `_all_dirty` is the safety valve:
        # it forces the old full rewrite, and _mark_modified -- the
        # central hook every structural mutation already calls -- sets
        # it.  So anything not specifically accounted for here still
        # writes everything, and only the hot path is optimised.
        self._dirty_props = set()
        self._all_dirty = True          # a new object has everything to write

    def __repr__(self) -> str:
        """String representation of object."""
        return f"MOOObject(#{self.objnum}, '{self.name}')"
        
    def __str__(self) -> str:
        """Human-readable string."""
        return f"#{self.objnum} ({self.name})"

    # ------------------------------------------------------------------
    # ``name`` — display-name property
    # ------------------------------------------------------------------
    # ``noun`` is the native atomic name (e.g. "sword", "Wizard").
    # ``name`` is a descriptor that returns the MOO property 'name' if
    # it has been set (typically by ``_title``), otherwise falls back to
    # ``noun``.  Setting ``name`` writes a MOO property through the
    # normal __setattr__ path (since 'name' is NOT in _NATIVE_ATTRS).

    @property
    def name(self) -> str:
        """Display name: local MOO property 'name' if set, else ``self.noun``.

        Unlike most properties, 'name' is NOT inherited.  Each object's
        display name is either its own local 'name' property (set by
        ``_title`` or direct assignment) or its ``noun``.  A parent's
        name should never bleed into its children.
        """
        props = self.__dict__.get('properties', {})
        if 'name' in props:
            return props['name'].value

        return self.noun

    def __eq__(self, other) -> bool:
        """Two MOOObjects are equal iff they share the same object number."""
        if isinstance(other, MOOObject):
            return self.objnum == other.objnum
        return NotImplemented

    def __hash__(self) -> int:
        """Hash by objnum so MOOObjects can be used in sets and as dict keys."""
        return hash(self.objnum)

    @property
    def contents(self) -> List['MOOObject']:
        """
        Return the objects inside this object as a list of MOOObjects.

        Falls back to returning the raw set of ints if no database
        reference is available (e.g. during construction).
        """
        db = self.__dict__.get('_database')
        if db is None:
            return list(self._content_ids)
        result = []
        for objnum in self._content_ids:
            try:
                result.append(db.get_object(objnum))
            except KeyError:
                pass
        return result

    @contents.setter
    def contents(self, value):
        """
        Accept a set/list of ints or MOOObjects for assignment.

        Args:
            value: Iterable of object numbers (int) or MOOObject instances.

        Notes:
            Duplicates are silently de-duped while preserving insertion order.
        """
        ids = []
        for item in value:
            # Accept either MOOObject instances or raw ints
            objnum = item.objnum if hasattr(item, 'objnum') else int(item)
            if objnum not in ids:
                ids.append(objnum)
        self._content_ids = ids
        self._mark_modified()

    @property
    def location(self) -> Optional['MOOObject']:
        """
        Return this object's location as a MOOObject, or None if nowhere.
        """
        if self._location_id == 0:
            return None
        db = self.__dict__.get('_database')
        if db is None:
            return None
        try:
            return db.get_object(self._location_id)
        except KeyError:
            return None

    @location.setter
    def location(self, value):
        """
        Set this object's location, updating both old and new containers.

        Accepts an int (object number), a MOOObject, ``None``, or ``0``
        (both meaning "nowhere").  Automatically removes this object from
        the old location's ``_content_ids`` and adds it to the new one,
        keeping the containment graph consistent.

        Args:
            value: New location as int, MOOObject, or None/0 for nowhere.

        Notes:
            For full move semantics (loop detection, timestamps), prefer
            ``move_to()`` instead of assigning ``location`` directly.
            This setter is used internally and for deserialization.
        """
        if value is None or value == 0:
            new_loc_id = 0
        elif isinstance(value, int):
            new_loc_id = value
        elif hasattr(value, 'objnum'):
            new_loc_id = value.objnum
        else:
            new_loc_id = int(value)

        # Remove from old location's contents
        old_loc_id = self._location_id
        db = self.__dict__.get('_database')
        if old_loc_id and old_loc_id != 0 and db:
            try:
                old_loc = db.get_object(old_loc_id)
                if self.objnum in old_loc._content_ids:
                    old_loc._content_ids.remove(self.objnum)
                old_loc._mark_modified()
            except Exception as e:
                logger.debug(f"Could not remove #{self.objnum} from old location #{old_loc_id}: {e}")

        # Add to new location's contents
        if new_loc_id != 0 and db:
            try:
                new_loc = db.get_object(new_loc_id)
                if self.objnum not in new_loc._content_ids:
                    new_loc._content_ids.append(self.objnum)
                new_loc._mark_modified()
            except Exception as e:
                logger.debug(f"Could not add #{self.objnum} to new location #{new_loc_id}: {e}")

        self._location_id = new_loc_id
        self._mark_modified()
    
    # ------------------------------------------------------------------
    # Object-reference serialisation helpers
    # ------------------------------------------------------------------
    # MOO properties can hold references to other objects.  At the Python
    # level these are live MOOObject instances, but they must be stored as
    # serialisable values.  The convention is:
    #   - Top-level MOOObject  ->  '#N' string (auto-resolved on read)
    #   - MOOObject in a list/dict  ->  plain int objnum
    # The asymmetry exists because top-level '#N' strings trigger the
    # auto-resolve path in ``_resolve_objref``, while lists/dicts already
    # use integer objnums by convention (e.g. ``wearing``, ``characters``).
    #
    # This serialiser only handles *live MOOObjects*.  ``'#N'`` reference
    # STRINGS are resolved to live objects at the input layer (the ``#N``
    # preprocessor for verb code, ``@set``, and the set_property JSON API),
    # so a reference has already become an object by the time it reaches here.

    @staticmethod
    def _store_objref(value):
        """Convert MOOObject values for property storage.

        Top-level MOOObjects become ``'#N'`` strings (auto-resolved on
        read).  MOOObjects nested inside lists or dicts become plain
        integer objnums, matching the existing convention for
        ``wearing``, ``characters``, ``contents``, etc.

        Args:
            value: Any property value, potentially containing MOOObjects.

        Returns:
            The same value with MOOObjects replaced by their serialisable
            representations.
        """
        if isinstance(value, MOOObject):
            return f"#{value.objnum}"
        if isinstance(value, _NullAttr):
            return None
        if isinstance(value, list):
            return [v.objnum if isinstance(v, MOOObject) else MOOObject._store_objref(v)
                    for v in value]
        if isinstance(value, dict):
            return {k: (v.objnum if isinstance(v, MOOObject) else MOOObject._store_objref(v))
                    for k, v in value.items()}
        return value

    def _resolve_objref(self, value, _prop=None, _root=None):
        """Auto-resolve ``'#N'`` string values to live MOOObject instances.

        Property values stored as ``'#123'`` are treated as object
        references and resolved via the database.  All other values
        (including strings that don't match the ``#N`` pattern) are
        returned unchanged.

        Args:
            value: The raw property value to potentially resolve.

        Returns:
            A MOOObject if the value matched ``'#N'`` and the object
            exists, otherwise the original *value* unchanged.

        Notes:
            Resolution silently falls through (returns the raw string)
            if the database is not attached or the referenced object
            does not exist.  This prevents errors during bootstrap or
            when objects have been recycled.
        """
        if isinstance(value, str) and len(value) > 1 and value[0] == '#' and value[1:].isdigit():
            db = self.__dict__.get('_database')
            if db:
                try:
                    return db.get_object(int(value[1:]))
                except (KeyError, Exception):
                    pass
            return value
        # Inside a list or dict, too.
        #
        # A reference only resolved when it was the whole value, so a room
        # whose `exits` held ['#14079'] got back a list of strings and
        # rendered "Obvious exits: none" -- every room in an imported world
        # disconnected, with nothing raising anywhere.
        #
        # Only '#N' strings resolve, so a list that genuinely holds numbers
        # is untouched, and so is one holding objnums the way
        # _store_objref writes them.  That matters for code ported from a
        # MOO: there OBJ is its own type, distinct from INT, and code
        # branches on the difference -- `typeof(elt) == INT` decides
        # whether an entry is a direction or an exit.  Handing back an
        # integer where the source had an object silently takes the wrong
        # branch.
        # A container read *from a property* comes back as a saver, so that
        # `obj.wear_list.insert(0, [])` stores the change instead of mutating
        # a copy and discarding it.  See moo/savers.py for why the copy has
        # to stay.  `_prop` is the property's name and is only passed by the
        # three read sites in __getattr__; every other caller -- and any
        # nested resolve without a binding -- still gets plain containers.
        if isinstance(value, list):
            if _prop is None:
                return [self._resolve_objref(v) for v in value]
            from .savers import SaverList
            out = SaverList()._bind(self, _prop, _root)
            root = _root if _root is not None else out
            for v in value:
                # list.append, not out.append: filling the container is not
                # a mutation of the property and must not write it back
                # forty-nine times on the way out.
                list.append(out, self._resolve_objref(v, _prop, root))
            return out
        if isinstance(value, dict):
            if _prop is None:
                return {k: self._resolve_objref(v) for k, v in value.items()}
            from .savers import SaverDict
            out = SaverDict()._bind(self, _prop, _root)
            root = _root if _root is not None else out
            for k, v in value.items():
                dict.__setitem__(out, k, self._resolve_objref(v, _prop, root))
            return out
        return value

    def msg(self, message: str = '', sub=None, dob=None, iob=None,
            uob=None, **kwargs):
        """
        Send *message* to this object, with emit substitution.

        The single most-called thing in a running world: every line of
        room description, every emote, and every combat message arrives
        through here, and ``msg_room`` calls it once per listener.

        Native, but still overridable.  ``msg`` used to be a three-line
        verb on #1 that did nothing but forward to ``notify()``, and it
        cost 168us to reach a 1.1us primitive -- about 150x overhead for a
        pass-through, multiplied by however many people are standing in
        the room.  What that bought was one genuinely valuable thing: an
        object could define its own ``msg`` and filter what it hears, which
        is how a deafened character stops hearing things.

        So the option is kept and the cost is not.  ``find_verb`` answers
        "does anything override this?" in 0.17us against a cache, and only
        an object that actually does one pays for a verb dispatch.  It is
        consulted per call, so a ``msg`` verb added at runtime takes effect
        immediately -- there is no cache here to go stale.

        There is deliberately no ``msg`` verb on #1 any more.  A default
        that lives in two places, one of which silently never runs, is the
        shape of bug that outlives everyone who understood it.

        Args:
            message: Message text.  Supports emit tokens (``&S``, ``&d``,
                ``&i``, ``&u`` and the pronoun forms) and the ``&0``/``&1``
                raw-string slots.
            sub: Subject object, for ``&s``/``&S`` and pronouns.
            dob: Direct object, for ``&d``/``&D``.
            iob: Indirect object, for ``&i``/``&I``.
            uob: Noun source, for ``&u``/``&U``.
            **kwargs: ``s0``/``s1``/... raw-string slots, passed through to
                the substitution engine.  Anything else is forwarded to an
                override verb and otherwise ignored.
        """
        from . import builtins as _builtins

        # Does this object -- or anything it inherits from -- override
        # messaging?  Almost nothing does, and asking is nearly free.
        db = self.__dict__.get('_database')
        if db is not None:
            try:
                _, verb_def = self.find_verb('msg', db)
            except Exception:
                verb_def = None
            if verb_def is not None:
                from .verb_context import verb_ctx
                ctx = verb_ctx.get(None)
                if ctx is not None:
                    pobj, ctx_db, depth = ctx
                    call = _builtins.make_call_verb(pobj, ctx_db, depth)
                    return call(self, 'msg', args=str(message), sub=sub,
                                dob=dob, iob=iob, uob=uob,
                                _pyargs=(message,), **kwargs)
                # No verb context to dispatch under (a ticker firing during
                # startup, say).  Falling through to notify is the right
                # failure: the player hears the line rather than nothing.

        # The raw-string slots the substitution engine reads as &0/&1/...
        svals = {k: v for k, v in kwargs.items()
                 if len(k) >= 2 and k[0] == 's' and k[1:].isdigit()}
        _builtins.notify(self, message, sub=sub, dob=dob, iob=iob, uob=uob,
                         svals=svals or None)

    def msg_room(self, message: str, exclude=None, **kwargs):
        """
        Send *message* to all players in this object's contents.

        Works like the builtin ``msg_room()`` but as a method, so verb
        code can write ``pobj.location.msg_room(...)`` naturally.

        Each recipient is messaged through its own ``msg`` verb, so any
        per-object override of ``msg`` applies to room broadcasts too.

        Args:
            message: Message text (supports &S/&d/&i emit substitution and
                &0/&1/... raw-string slots).
            exclude: List of objects to exclude from receiving the message.
            **kwargs: Optional sub, dob, iob, uob for emit substitution, plus
                s0/s1/... raw-string slots (&N).
        """
        exclude_nums = set()
        for obj in (exclude or []):
            exclude_nums.add(obj.objnum if hasattr(obj, 'objnum') else obj)

        sub = kwargs.get('sub')
        if sub is None:
            # Default the subject to whoever is acting.
            #
            # A room broadcast is nearly always about the actor, and
            # forgetting sub= fails silently: &S renders as nothing, and
            # the room is told that somebody did something.  @tel shipped
            # that way for as long as it had existed, and the workaround
            # in the world was to hardcode a name into the message, which
            # then went stale the moment the character was renamed.
            #
            # 80 of the 87 msg_room calls in the shipped verbs already
            # pass sub= explicitly, so this fills a gap rather than
            # changing a convention; naming a different subject still wins.
            try:
                from .verb_context import verb_ctx
                _ctx = verb_ctx.get(None)
                if _ctx:
                    sub = _ctx[0]
            except Exception:
                pass
        dob = kwargs.get('dob')
        iob = kwargs.get('iob')
        uob = kwargs.get('uob')
        # Raw-string slots (s0=, s1=, ...) -> esub %N.  Passed straight
        # through as sN kwargs, which is what the msg verb expects.
        slots = {k: v for k, v in kwargs.items()
                 if len(k) >= 2 and k[0] == 's' and k[1:].isdigit()}

        if hasattr(self, 'contents'):
            for obj in self.contents:
                if obj.objnum not in exclude_nums:
                    try:
                        if obj.is_player:
                            # Deliver through msg, not notify.  msg is a verb
                            # and overridable per object, which is how a
                            # deafened or filtered character stops hearing
                            # things; calling notify directly walked straight
                            # past every one of those overrides.
                            obj.msg(message, sub=sub, dob=dob, iob=iob,
                                    uob=uob, **slots)
                    except Exception:
                        pass

    def __getattr__(self, name: str) -> Any:
        """
        Attribute access sugar for MOO properties and verbs.

        This is only called when normal Python attribute lookup has
        already failed, so it will never shadow real attributes like
        ``name``, ``parent``, ``location``, ``contents``, etc.
        
        Lookup order:
        
        1. MOO properties (local, then inherited via cache).
        2. Verbs — returns a callable wrapper so verb code can use
           natural method syntax::
        
               this._title()
               result = chest.is_locked()
               npc.react('angry')
        
        The verb wrapper reads the active player/db from the
        thread-local verb context (set automatically when any verb
        or eval begins execution).
        
        Returns:
            Property value, verb callable, or None if not found.
        """
        # Guard: skip dunder names entirely, and bail if
        # properties dict hasn't been set yet (mid-__init__).
        if name.startswith('__') or 'properties' not in self.__dict__:
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            )
        
        # --- Property lookup (skip single-underscore names) ---
        if not name.startswith('_'):
            # Check local properties
            props = self.__dict__['properties']
            if name in props:
                return self._resolve_objref(props[name].value, name)

            # Check the flattened inheritance cache
            if self.__dict__.get('_inheritance_cache_valid') and self.__dict__.get('_resolved_properties'):
                resolved = self.__dict__['_resolved_properties']
                if name in resolved:
                    prop_info, _defining_objnum = resolved[name]
                    return self._resolve_objref(prop_info.value, name)
            else:
                # Try to build cache if we have a database reference
                db = self.__dict__.get('_database')
                if db:
                    self._ensure_cache(db)
                    resolved = self.__dict__.get('_resolved_properties')
                    if resolved and name in resolved:
                        prop_info, _defining_objnum = resolved[name]
                        return self._resolve_objref(prop_info.value, name)
        
        # --- Verb lookup (walks inheritance) ---
        db = self.__dict__.get('_database')
        if db:
            defining_objnum, verb_def = self.find_verb(name, db)
            if verb_def is not None:
                return self._make_verb_callable(name, db)
        
        if name.startswith('_'):
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            )
        # Missing MOO property.  MOO raises E_PROPNF here, and so do we.
        #
        # This used to return a falsy sentinel so that `if pobj.rt > 0:`
        # worked without declaring rt anywhere.  That is convenient and it
        # is wrong, in the way that costs most: a misspelled property name
        # reads as nothing and travels, and the failure surfaces somewhere
        # else entirely.  It also broke every port of MOO code, since MOO
        # code is written knowing a missing property is an error -- the
        # backtick catch `x.foo ! E_PROPNF => 0' had to be special-cased
        # in catch() to work at all, which was the sign that the two
        # models were fighting.
        #
        # The replacement for the old idiom is to declare the property
        # with a default on the parent, which is what MOO does and what
        # the prototype hierarchy is for.
        # PropertyNotFound is both a MOOError and an AttributeError, so
        # a ported verb catches it as E_PROPNF and engine Python reads
        # through it with getattr(obj, name, default) as usual.
        from .properties import PropertyNotFound
        raise PropertyNotFound(
            f'#{self.objnum}.{name} is not defined')
    
    def _make_verb_callable(self, verb_name: str, db):
        """
        Return a callable wrapper that invokes *verb_name* on this object.

        The wrapper reads the active player and database from the
        thread-local verb context (set automatically when any verb or
        ``eval`` begins execution).  This enables natural method-call
        syntax in verb code::

            chest.is_locked()       # calls verb 'is_locked' on chest
            npc.react('angry')      # passes 'angry' as the args string

        Args:
            verb_name (str): Name of the verb to wrap.
            db: Database reference (currently unused inside the closure
                but available for future optimisations).

        Returns:
            A callable that, when invoked, dispatches through the
            ``call_verb`` machinery with proper depth tracking.

        Raises:
            RuntimeError: If called outside of an active verb context.
            RecursionError: If the verb call depth exceeds MAX_VERB_DEPTH.
        """
        obj = self

        def _call_verb(*args, **kwargs):
            from .verb_context import verb_ctx, set_verb_context, clear_verb_context, MAX_VERB_DEPTH
            from . import builtins as _builtins

            # Read the thread-local verb context to find the acting player
            ctx = verb_ctx.get(None)
            if ctx is None:
                raise RuntimeError(
                    f"Cannot call verb '{verb_name}' on #{obj.objnum}: "
                    f"no active verb context (use call_verb() outside of verb/eval execution)"
                )

            pobj, ctx_db, depth = ctx

            # Guard against infinite verb recursion
            if depth >= MAX_VERB_DEPTH:
                raise RecursionError(
                    f"Verb call depth exceeded {MAX_VERB_DEPTH}: "
                    f"{verb_name} on #{obj.objnum}"
                )

            # Support positional args: npc.react('angry') becomes args='angry'
            arg_str = ''
            if args:
                arg_str = ' '.join(str(a) for a in args)
                kwargs['_pyargs'] = args  # Preserve typed args for the verb

            # Delegate to the standard call_verb machinery (handles context
            # push/pop, depth increment, verb lookup, etc.)
            call_verb_fn = _builtins.make_call_verb(pobj, ctx_db, depth)
            return call_verb_fn(obj, verb_name, args=arg_str, **kwargs)

        return _call_verb
    
    # ------------------------------------------------------------------
    # Native attribute whitelist
    # ------------------------------------------------------------------
    # Names listed here are stored directly on the Python instance via
    # ``object.__setattr__`` and are NOT routed through the MOO property
    # system.  Everything NOT in this set and NOT starting with '_' is
    # treated as a MOO property assignment by ``__setattr__``.
    #
    # Note: 'name', 'location', 'contents', and 'parent' are NOT in
    # this set because they have dedicated property descriptors or
    # special handling inside ``__setattr__``.
    _NATIVE_ATTRS = frozenset({
        'objnum', 'children', 'noun', 'aliases', 'owner',
        'flags', 'properties',
        'verbs', 'created', 'last_move', 'tags',
    })

    # Native attributes a verb may not write unless it runs as a wizard.
    #
    # These are not properties, so they never reach the property
    # permission check -- they go straight to object.__setattr__.  That
    # made them the shortest escalation in the engine: `pobj.flags = 4`
    # sets the WIZARD bit outright, and `pobj.owner = me` takes ownership
    # of whatever it is written on, after which every other check agrees
    # you were entitled all along.
    _PRIVILEGED_ATTRS = frozenset({'flags', 'owner'})

    # Properties a verb may not write unless it runs as a wizard.
    #
    # `auth` carries staff level, and the engine reads it: auth_level()
    # derives authority from it and sync_auth_flags() promotes the
    # PROGRAMMER / WIZARD flags to match.  Writing it is therefore the
    # same act as setting those flags, one step removed.
    #
    # It cannot be distinguished by permissions -- on #3, `auth` and `rt`
    # are both 'rc' owned by 0, and a player must be able to write their
    # own `rt`.  The difference is meaning, not bits, and the engine is
    # already the thing that knows what `auth` means.
    _PRIVILEGED_PROPS = frozenset({'auth'})
    
    def __setattr__(self, name: str, value: Any):
        """
        Attribute assignment sugar for MOO properties.
        
        Private/dunder names and the core MOOObject attributes (``noun``,
        ``parent``, ``location``, etc.) are handled normally.  Everything
        else is routed to the MOO property system::
        
            obj.damage = 25        # sets/creates MOO property 'damage'
            obj.name = "A Sword"   # sets/creates MOO property 'name'
            obj.noun = "Sword"     # sets the Python attribute (native)
            obj._foo = 1           # sets the Python attribute (private)
        
        If the property already exists (locally or inherited), its value
        is updated.  If it does not exist, a new local property is
        created with default permissions ('rc').
        """
        # Private/dunder attrs and core native attrs: normal Python path
        if name.startswith('_') or name in MOOObject._NATIVE_ATTRS:
            if name in MOOObject._PRIVILEGED_ATTRS:
                self._check_privileged(name)
            object.__setattr__(self, name, value)
            # Auto-save native attr changes (no-op during init/from_dict
            # when _database is None)
            if not name.startswith('_') and self.__dict__.get('_database'):
                self._auto_save_to_db()
            return
        
        # 'contents' and 'location' are property descriptors — route to setters
        if name == 'contents':
            type(self).contents.fset(self, value)
            return
        if name == 'location':
            type(self).location.fset(self, value)
            return
        # 'parent' assignment — update old/new parent children lists
        if name == 'parent':
            db = self.__dict__.get('_database')
            if db:
                old_parent_num = self.__dict__.get('parent', 0)
                new_parent_num = value.objnum if hasattr(value, 'objnum') else int(value) if value else 0
                if old_parent_num and old_parent_num != 0:
                    try:
                        old_parent_obj = db.get_object(old_parent_num)
                        old_parent_obj.children.discard(self.objnum)
                        old_parent_obj._mark_modified()
                    except (KeyError, Exception):
                        pass
                if new_parent_num != 0:
                    try:
                        new_parent_obj = db.get_object(new_parent_num)
                        new_parent_obj.children.add(self.objnum)
                        new_parent_obj._mark_modified()
                    except (KeyError, Exception):
                        pass
                object.__setattr__(self, name, new_parent_num)
                self.invalidate_inheritance_cache(db)
                self._mark_modified()
                return
            # No database (during init/from_dict) — just set it
            object.__setattr__(self, name, value)
            return
        
        # If __init__ hasn't finished (no 'properties' dict yet): normal
        if 'properties' not in self.__dict__:
            object.__setattr__(self, name, value)
            return
        
        # --- MOO property assignment ---
        props = self.__dict__['properties']
        db = self.__dict__.get('_database')
        value = self._store_objref(value)

        # Update existing local property
        if name in props:
            self._check_write(name, props[name])
            props[name].value = value
            self.__dict__['_dirty_props'].add(name)
            self._invalidate_local()
            self._auto_save_to_db(db)
            return

        # Check inheritance cache for an inherited property to override
        if db:
            self._ensure_cache(db)
        resolved = self.__dict__.get('_resolved_properties')
        if resolved and name in resolved:
            # Inherited property exists — create a local override
            inherited_info, _defining_obj = resolved[name]
            self._check_write(name, inherited_info)
            self.add_property(name, value=value, perms=inherited_info.perms)
            return

        # Brand-new property — the privileged-name gate, then ownership.
        #
        # `_check_privileged` first, so all three write paths agree. The
        # other two reach it through `_check_write` (lines 1199 and 1213);
        # this one checked ownership alone, which made creating a
        # privileged name the one way into this class of property that
        # skipped the auth check.
        #
        # Not reachable today -- a name like `auth` is declared on #3, so
        # writing it to a character always takes the inherited-override
        # path above, and creating one on an object that does *not*
        # inherit it escalates nothing. This closes the asymmetry rather
        # than a hole: three paths to the same decision should not be
        # two-thirds guarded, because the next privileged name added may
        # not have a declaration to fall back on.
        self._check_privileged(name)
        from .verb_context import verb_ctx
        ctx = verb_ctx.get(None)
        if ctx is not None:
            pobj, _, _ = ctx
            is_wizard = getattr(pobj, 'is_wizard', False)
            if not is_wizard and getattr(pobj, 'objnum', None) != self.owner:
                raise PermissionError(
                    f"Permission denied: cannot create '{name}' on #{self.objnum}"
                )
        self.add_property(name, value=value, perms='rc')
    
    def _check_privileged(self, name):
        """
        Refuse a native-attribute write that only a wizard may make.

        Covers ``flags`` and ``owner`` -- see ``_PRIVILEGED_ATTRS``.
        Engine-level writes (startup, migration, ``from_dict``, tests)
        run with no verb context and are allowed; only code executing as
        a verb is held to this.

        Args:
            name (str): The attribute being written.

        Raises:
            PermissionError: If the running verb is not a wizard.
        """
        try:
            from .builtins import current_perms
            actor = current_perms()
        except Exception:
            return
        if actor is None:
            return                      # not inside a verb
        db = self.__dict__.get('_database')
        if db is None:
            return
        try:
            if getattr(db.get_object(actor), 'is_wizard', False):
                return
        except Exception:
            return
        raise PermissionError(
            f"Permission denied: cannot set '{name}' on #{self.objnum}"
        )

    def _check_add(self, name):
        """Refuse creating a property on an object the actor does not own.

        The companion to :meth:`_check_write`, for the case where there is
        no permission record yet because the property does not exist.  Same
        actor, same wizard exemption; ownership of the object stands in for
        the property's own perms.
        """
        if name in MOOObject._PRIVILEGED_PROPS:
            self._check_write(name, self.properties.get(name))
            return
        try:
            from .builtins import current_perms
            actor = current_perms()
        except Exception:
            return
        if actor is None:
            return                      # engine-level: no player to check
        db = self.__dict__.get('_database')
        if db is not None:
            try:
                if getattr(db.get_object(actor), 'is_wizard', False):
                    return
            except Exception:
                return
        if actor == self.owner:
            return
        raise PermissionError(
            f"Permission denied: cannot add '{name}' to #{self.objnum}"
        )

    def _check_write(self, name, prop_info):
        """
        Refuse a property write the running verb is not entitled to make.

        ``obj.x = v`` used to be entirely ungated while ``setattr(obj,
        'x', v)`` was checked, so the permission model was decoration:
        every verb simply used the assignment form.  ``pobj.flags = 4``
        was wizard, and ``pobj.auth = ['gm5']`` was too.

        The check runs against the *verb owner* -- who the running verb
        acts as -- not the player who typed the command.  That is the MOO
        model, and it is what keeps ordinary play working: staff own both
        the verbs and the properties, so a staff verb writing a player's
        stats is the owner writing its own property.  A player-authored
        verb reaching for someone else's property is not.

        Outside a verb entirely -- engine startup, migrations, tests --
        there is nobody to check against and the write proceeds.

        Args:
            name (str): Property being written.
            prop_info (PropertyInfo): Its permission record.

        Raises:
            PermissionError: If the running verb may not write it.
        """
        try:
            from .builtins import current_perms
            actor = current_perms()
        except Exception:
            return
        if actor is None:
            return                      # no verb context: engine-level write
        db = self.__dict__.get('_database')
        is_wizard = False
        if db is not None:
            try:
                is_wizard = bool(getattr(db.get_object(actor), 'is_wizard', False))
            except Exception:
                is_wizard = False
        if is_wizard:
            return
        if name in MOOObject._PRIVILEGED_PROPS:
            raise PermissionError(
                f"Permission denied: cannot write '{name}' on #{self.objnum}"
            )
        # 'c' is chown: a descendant's copy of an inherited property
        # belongs to that descendant's owner, so the object's owner may
        # write it.  This is what lets a player's own verb set their own
        # character's `rt` -- the property is declared up on #3 and owned
        # by the system, but the copy being written is theirs.
        if prop_info.is_inherited and actor == self.owner:
            return
        if not prop_info.can_write(actor, is_wizard):
            raise PermissionError(
                f"Permission denied: cannot write '{name}' on #{self.objnum}"
            )

    def _auto_save_to_db(self, db=None):
        """
        Persist this object to the database (best-effort).

        Called automatically after property mutations when auto-save is
        implicitly enabled (via having a ``_database`` reference).  Errors
        are swallowed so that a database hiccup never breaks a property
        assignment in the middle of verb execution.

        Args:
            db: Database to use.  Falls back to ``self._database``.
        """
        if db is None:
            db = self.__dict__.get('_database')
        if db:
            try:
                db.save_object(self)
            except Exception as e:
                logger.warning(f"Auto-save failed for #{self.objnum}: {e}")
    
    def _invalidate_local(self):
        """
        Mark this object's inheritance cache dirty and propagate downward.

        Called after a direct property value change (as opposed to a
        structural change like adding/removing a property).  Ensures
        that any descendant caching our property values will rebuild
        on their next access.
        """
        self.__dict__['_inheritance_cache_valid'] = False
        self.__dict__['_cache_dirty'] = True
        # Propagate to descendants so they see the new value
        db = self.__dict__.get('_database')
        if db:
            self.invalidate_inheritance_cache(db)
    
    # ========================================================================
    # AUTO-SAVE FUNCTIONALITY
    # ========================================================================
    
    def enable_auto_save(self, database=None):
        """
        Enable automatic saving after modifications.
        
        Args:
            database: Database instance for saving (optional)
        """
        self._auto_save = True
        if database:
            self._database = database
        logger.debug(f"Auto-save enabled for #{self.objnum}")
    
    def disable_auto_save(self):
        """Disable automatic saving (for batch operations)."""
        self._auto_save = False
        logger.debug(f"Auto-save disabled for #{self.objnum}")
    
    def _mark_modified(self, value_only: bool = False):
        """
        Central mutation hook: invalidate caches and persist.

        Every method that mutates the object's state (property changes,
        moves, parent changes, etc.) calls this.  It:
        1. Invalidates the inheritance cache (and descendants).
        2. Auto-saves to the database if enabled.
        3. Sets ``_pending_save`` if auto-save is off, so a later
           explicit ``save()`` call knows work is pending.

        Args:
            value_only: True when the change was one property's *value*
                and the caller has already named it in ``_dirty_props``.
                Everything else -- a new property, a verb, a reparent --
                leaves the object marked wholly dirty, so a save it did
                not anticipate still writes everything.  That default is
                what makes the targeted write path safe to add.
        """
        if not value_only:
            self.__dict__['_all_dirty'] = True
        self.invalidate_inheritance_cache()
        if self._auto_save and self._database:
            try:
                self._database.save_object(self)
                logger.debug(f"Auto-saved #{self.objnum}")
            except Exception as e:
                logger.error(f"Auto-save failed for #{self.objnum}: {e}")
        else:
            self._pending_save = True
            
    def save(self, database=None):
        """
        Manually save this object to database.
        
        Args:
            database: Database to save to (uses _database if not provided)
        """
        db = database or self._database
        if db:
            db.save_object(self)
            self._pending_save = False
            logger.debug(f"Manually saved #{self.objnum}")
        else:
            logger.warning(f"Cannot save #{self.objnum}: no database reference")
    
    # ========================================================================
    # INHERITANCE CACHE
    # ========================================================================
    
    def _build_inheritance_cache(self, database=None):
        """
        Build the flattened inheritance cache by walking the parent chain.
        
        The resolved tables map every inherited + local name to its value
        and the object number where it was defined.  Local definitions
        override parent definitions, matching standard MOO semantics.
        
        After this call, ``get_property`` and ``find_verb`` become O(1)
        dict lookups until the cache is invalidated.
        """
        db = database or self._database
        
        # Collect the ancestor chain (self first, root last)
        # Also repair children lists along the way.
        # Track visited objnums to detect circular parent chains.
        chain: List['MOOObject'] = [self]
        visited: Set[int] = {self.objnum}
        current = self
        while current.parent and db:
            if current.parent in visited:
                logger.error(
                    f"Circular parent chain detected: #{current.objnum} "
                    f"points to #{current.parent} which is already in the "
                    f"chain for #{self.objnum}"
                )
                break
            try:
                parent_obj = db.get_object(current.parent)
                visited.add(parent_obj.objnum)
                # Ensure parent knows about this child
                if current.objnum not in parent_obj.children:
                    parent_obj.children.add(current.objnum)
                current = parent_obj
                chain.append(current)
            except (KeyError, AttributeError):
                break
        
        # Walk from root → self so that child definitions override parents
        resolved_props: Dict[str, Tuple[PropertyInfo, int]] = {}
        resolved_verbs: Dict[str, Tuple[Any, int]] = {}
        
        for ancestor in reversed(chain):
            # Properties: include those marked as inherited ('c' perm),
            # or all properties if this is the object itself
            for name, prop in ancestor.properties.items():
                if ancestor is self or prop.is_inherited:
                    resolved_props[name] = (prop, ancestor.objnum)
                    
            # Verbs: all verbs are inherited in MOO
            for verb in ancestor.verbs:
                for vname in verb.matchable_names():
                    resolved_verbs[vname] = (verb, ancestor.objnum)
        
        # --- Names that mean two things -------------------------------
        #
        # __getattr__ resolves properties before verbs, so a property
        # named like a verb wins and the verb becomes unreachable through
        # attribute access.  Nothing fails at that point.  The failure is
        # later and somewhere else, as `TypeError: 'str' object is not
        # callable` at the call site, which says nothing about the name
        # having been taken.  Say it here, where both definitions are in
        # hand and we know which object each came from.
        #
        # Canonical verb names only.  matchable_names() expands
        # abbreviations, so intersecting against those would report a
        # property called `exam` as shadowing `examine` -- true, and not
        # worth anybody's attention.
        for _vname, (_verb, _vfrom) in resolved_verbs.items():
            if _vname not in resolved_props or _vname not in _verb.names:
                continue
            _key = (self.objnum, _vname)
            if _key in _reported_shadowed_verbs:
                continue
            _reported_shadowed_verbs.add(_key)
            # debug, not warning.  The shipped world does this on purpose
            # and five times over: a verb's message lives in a property
            # named after the verb -- #22.open is "You open &d." beside
            # the open verb, and #15.x is a map coordinate beside the x
            # verb.  Warning on every boot about the engine's own
            # convention is crying wolf.  What this is for is the hour
            # you spend on `TypeError: 'str' object is not callable`
            # with no idea which name was taken: turn on debug logging
            # and the answer is already written down.
            logger.debug(
                "#%s.%s is both a property (from #%s) and a verb (from #%s); "
                "the property wins, so the verb is reachable only as "
                "call_verb(obj, %r)",
                self.objnum, _vname, resolved_props[_vname][1], _vfrom, _vname)

        self._resolved_properties = resolved_props
        self._resolved_verbs = resolved_verbs
        self._inheritance_cache_valid = True
        self._cache_dirty = False
        
        # Track stats in the database
        if self._database and hasattr(self._database, '_inheritance_cache_builds'):
            self._database._inheritance_cache_builds += 1
        
        logger.debug(
            f"Built inheritance cache for #{self.objnum}: "
            f"{len(resolved_props)} props, {len(resolved_verbs)} verbs"
        )
    
    def _ensure_cache(self, database=None):
        """Build the inheritance cache if it is not currently valid."""
        if not self._inheritance_cache_valid:
            self._build_inheritance_cache(database)
    
    def invalidate_inheritance_cache(self, database=None, _visited: Optional[Set[int]] = None):
        """
        Invalidate this object's inheritance cache and propagate to all
        descendants.

        This is the key correctness mechanism: whenever a property or verb
        is added, removed, or modified on an object, every descendant that
        might have cached the old resolved value must be told to rebuild
        on next access.

        Uses the children list for propagation, then sweeps all in-memory
        objects as a safety net in case children lists are out of sync
        with parent pointers.

        Args:
            database: Database for resolving children (uses self._database
                      if not provided)
            _visited: Internal set to prevent infinite recursion
        """
        if _visited is None:
            _visited = set()
        if self.objnum in _visited:
            return
        _visited.add(self.objnum)

        self._inheritance_cache_valid = False
        self._resolved_properties = None
        self._resolved_verbs = None
        self._cache_dirty = True

        db = database or self._database
        if not db:
            return

        # Under bulk_load() the sweep is deferred -- see the note there.
        if _BULK_LOAD:
            return

        # Propagate via children list
        for child_objnum in list(self.children):
            try:
                child = db.get_object(child_objnum)
                child.invalidate_inheritance_cache(db, _visited)
            except (KeyError, AttributeError):
                pass

    
    # ========================================================================
    # ATTRIBUTE SETTERS WITH AUTO-SAVE
    # ========================================================================
    
    def set_name(self, new_name: str):
        """
        Set object name and trigger auto-save.
        
        Args:
            new_name: New name for the object
        """
        self.name = new_name
        self._mark_modified()
    
    def set_location(self, new_location: int):
        """
        Set object location (without full move logic) and trigger auto-save.
        
        For full move semantics, use move_to() instead.
        
        Args:
            new_location: New location object number
        """
        old_location = self._location_id
        self._location_id = new_location
        self.last_move = time.time()
        self._mark_modified()
        logger.debug(f"#{self.objnum} location changed from #{old_location} to #{new_location}")
    
    def set_parent(self, new_parent: int):
        """
        Set object parent and trigger auto-save.
        
        Args:
            new_parent: New parent object number
        """
        old_parent = self.parent
        self.parent = new_parent
        self.invalidate_inheritance_cache()
        self._mark_modified()
        logger.debug(f"#{self.objnum} parent changed from #{old_parent} to #{new_parent}")
        
    # ========================================================================
    # FLAG MANAGEMENT
    # ========================================================================
    
    def has_flag(self, flag: ObjectFlags) -> bool:
        """
        Test whether a specific flag is set on this object.

        Args:
            flag (ObjectFlags): The flag constant to test.

        Returns:
            bool: ``True`` if the flag bit is set.
        """
        return bool(self.flags & flag)

    def set_flag(self, flag: ObjectFlags):
        """
        Enable a flag on this object (bitwise OR).

        Args:
            flag (ObjectFlags): The flag constant to set.
        """
        self.flags |= flag

    def clear_flag(self, flag: ObjectFlags):
        """
        Disable a flag on this object (bitwise AND with complement).

        Args:
            flag (ObjectFlags): The flag constant to clear.
        """
        self.flags &= ~flag
        
    @property
    def is_player(self) -> bool:
        """Check if this is a player object (connected or connectable).

        Returns:
            bool: ``True`` if the PLAYER flag is set.
        """
        return self.has_flag(ObjectFlags.PLAYER)

    @property
    def is_wizard(self) -> bool:
        """Check if this object has wizard (superuser) privileges.

        Returns:
            bool: ``True`` if the WIZARD flag is set.
        """
        return self.has_flag(ObjectFlags.WIZARD)

    @property
    def is_programmer(self) -> bool:
        """Check if this object can create and edit verb code.

        Wizards implicitly have programmer rights even without the
        PROGRAMMER flag being set explicitly.

        Returns:
            bool: ``True`` if PROGRAMMER or WIZARD flag is set.
        """
        return self.has_flag(ObjectFlags.PROGRAMMER) or self.is_wizard

    @property
    def is_fertile(self) -> bool:
        """Check if this object can be used as a parent for new objects.

        Wizards can always parent from any object regardless of the
        FERTILE flag.

        Returns:
            bool: ``True`` if FERTILE or WIZARD flag is set.
        """
        return self.has_flag(ObjectFlags.FERTILE) or self.is_wizard
        
    # ========================================================================
    # PLAYER MESSAGING
    # ========================================================================

    def docstring(self, string: str):
        """
        Send a formatted usage/help string with a bordered display.

        Wraps the given *string* in horizontal rule borders (using
        ANSI color code 245 for a subdued grey) and sends it to this
        object via ``notify()``.  Primarily used by verbs that want
        to display a usage/help block to the player.

        Args:
            string (str): Multi-line help text to display.  The border
                width is auto-calculated from the longest line.
        """
        from .builtins import notify
        # Calculate border width from the longest line in the string
        width = max(len(line) for line in string.split('\n'))
        border = f"&<245>{'=' * width}&n"
        notify(self, f"{border}\n{string}\n{border}")

    # ========================================================================
    # PROPERTY MANAGEMENT
    # ========================================================================
    
    def add_property(self, name: str, value: Any = None,
                     owner: Optional[int] = None, perms: str = "rc"):
        """
        Add a new property to this object.

        Args:
            name: Property name
            value: Initial value (MOOObject values auto-convert to '#N')
            owner: Owner object number (default: this object's owner)
            perms: Permission string (default: "rc")

        Raises:
            ValueError: If property already exists
        """
        # See set_property.  A brand-new property has no permission record
        # to consult, so the question is about the *object*: may you add
        # something to this one?  Ownership answers it, which is the same
        # rule the other two paths end up applying.
        #
        # Without this, `@adprop #0.startup_evals = [...]` created a
        # property on the system object -- whose entries then run at boot as
        # #0, carrying WIZARD -- for anybody who could type it.  The
        # privileged-name gate did not catch it because the name was new,
        # and there is always another name.
        self._check_add(name)
        if name in self.properties:
            raise ValueError(f"Property '{name}' already exists on #{self.objnum}")

        if owner is None:
            owner = self.owner

        value = self._store_objref(value)
        self.properties[name] = PropertyInfo(
            name=name,
            value=value,
            owner=owner,
            perms=perms
        )
        self.invalidate_inheritance_cache()
        self._mark_modified()  # AUTO-SAVE
        logger.debug(f"Added property '{name}' to #{self.objnum}")
        
    def delete_property(self, name: str):
        """
        Delete a property from this object.
        
        Args:
            name: Property name to delete
            
        Raises:
            KeyError: If property doesn't exist on this object
        """
        # See set_property.  Removing somebody's `auth` is the same
        # privilege action in the other direction, and @rmprop reaches here.
        if name in self.properties:
            self._check_write(name, self.properties[name])
        if name not in self.properties:
            raise KeyError(f"Property '{name}' not found on #{self.objnum}")
            
        del self.properties[name]
        self.invalidate_inheritance_cache()
        self._mark_modified()  # AUTO-SAVE
        logger.debug(f"Deleted property '{name}' from #{self.objnum}")
        
    def has_property(self, name: str, local_only: bool = False, database=None) -> bool:
        """
        Check if object has a property (including inherited).
        
        Args:
            name: Property name
            local_only: If True, don't check parent objects
            database: Database for parent resolution
            
        Returns:
            bool: True if property exists
        """
        if name in self.properties:
            return True
            
        if local_only:
            return False
            
        # Use flattened inheritance cache for O(1) lookup
        db = database or self._database
        self._ensure_cache(db)
        if self._resolved_properties is not None:
            return name in self._resolved_properties
        
        # Fallback: walk the parent chain (no database available)
        return False
        
    def get_property(self, name: str, database=None) -> Any:
        """
        Get property value, resolving through inheritance chain.
        
        Uses the flattened inheritance cache for O(1) lookups when
        available.  Falls back to a parent-chain walk if the cache
        cannot be built (no database reference).
        
        Args:
            name: Property name
            database: Database object for resolving parent properties
            
        Returns:
            Property value
            
        Raises:
            KeyError: If property not found in this object or any parent
        """
        # Fast path: check local properties first (avoids cache build
        # for the common case of locally-defined properties)
        if name in self.properties:
            return self.properties[name].value
        
        # Use flattened inheritance cache
        db = database or self._database
        self._ensure_cache(db)
        if self._resolved_properties is not None and name in self._resolved_properties:
            prop_info, _defining_objnum = self._resolved_properties[name]
            return prop_info.value
                
        raise KeyError(f"Property '{name}' not found on #{self.objnum}")
        
    def set_property(self, name: str, value: Any, database=None):
        """
        Set property value.

        Args:
            name: Property name
            value: New value (MOOObject values auto-convert to '#N')
            database: Database object for resolving inherited properties

        Raises:
            KeyError: If property doesn't exist
        """
        db = database or self._database
        value = self._store_objref(value)

        # The same check `__setattr__` makes.  These three methods used not
        # to make it, and @set, @adprop and @rmprop all reach the property
        # system through them rather than through the attribute sugar -- so
        # the permission model was enforced on `obj.x = v` and not on the
        # commands, which is the way round that matters.
        #
        # This only bites now that those commands open with
        # `set_task_perms(caller_perms())`.  Before that they acted as their
        # staff owner, the check passed, and adding it here changed nothing:
        # tried, watched a gm3 promote itself straight through it, and the
        # reason was that the check asks who the *verb* acts as.
        if name in self.properties:
            self._check_write(name, self.properties[name])
        elif db is not None and self.has_property(name, local_only=False,
                                                  database=db):
            try:
                parent_obj = db.get_object(self.parent)
                self._check_write(name, parent_obj.get_property_info(name, db))
            except (KeyError, AttributeError):
                pass

        # If property exists locally, set it
        if name in self.properties:
            self.properties[name].value = value
            self.__dict__['_dirty_props'].add(name)
            self.invalidate_inheritance_cache()
            self._mark_modified(value_only=True)  # AUTO-SAVE
            return
            
        # If property is inherited, create local override
        if self.has_property(name, local_only=False, database=db):
            # Get property info from parent to copy metadata
            if self.parent and db:
                parent_obj = db.get_object(self.parent)
                try:
                    parent_prop = parent_obj.get_property_info(name, db)
                    # Create local copy with new value
                    self.add_property(
                        name=name,
                        value=value,
                        owner=self.owner,
                        perms=parent_prop.perms
                    )
                    # AUTO-SAVE and invalidation triggered by add_property
                    return
                except KeyError:
                    pass
                    
        raise KeyError(f"Property '{name}' not found on #{self.objnum}")
        
    def get_property_info(self, name: str, database=None) -> PropertyInfo:
        """
        Get property metadata.
        
        Args:
            name: Property name
            database: Database for parent resolution
            
        Returns:
            PropertyInfo: Property metadata
            
        Raises:
            KeyError: If property not found
        """
        if name in self.properties:
            return self.properties[name]
        
        # Use flattened inheritance cache
        db = database or self._database
        self._ensure_cache(db)
        if self._resolved_properties is not None and name in self._resolved_properties:
            prop_info, _defining_objnum = self._resolved_properties[name]
            return prop_info
            
        raise KeyError(f"Property '{name}' not found on #{self.objnum}")
        
    def properties_list(self, include_inherited: bool = True, database=None) -> List[str]:
        """
        Get list of property names.
        
        Args:
            include_inherited: Include properties from parent chain
            database: Database for parent resolution
            
        Returns:
            List of property names
        """
        if not include_inherited:
            return sorted(self.properties.keys())
        
        # Use flattened inheritance cache for the full list
        db = database or self._database
        self._ensure_cache(db)
        if self._resolved_properties is not None:
            return sorted(self._resolved_properties.keys())
        
        # Fallback: local only (no database available to resolve parents)
        return sorted(self.properties.keys())
        
    # ========================================================================
    # VERB MANAGEMENT
    # ========================================================================
    
    def add_verb(self, verb_def):
        """
        Add a verb to this object.

        Args:
            verb_def: VerbDef object (from verbs module)
        """
        self.verbs.append(verb_def)
        self.invalidate_inheritance_cache()
        self._mark_modified()  # AUTO-SAVE
        logger.debug(f"Added verb '{verb_def.names[0]}' to #{self.objnum}")
        
    def delete_verb(self, verb_name: str):
        """
        Delete a verb from this object.
        
        Args:
            verb_name: Name of verb to delete
            
        Raises:
            KeyError: If verb not found
        """
        for i, verb in enumerate(self.verbs):
            if verb_name in verb.names:
                del self.verbs[i]
                self.invalidate_inheritance_cache()
                self._mark_modified()  # AUTO-SAVE
                logger.debug(f"Deleted verb '{verb_name}' from #{self.objnum}")
                return
                
        raise KeyError(f"Verb '{verb_name}' not found on #{self.objnum}")
        
    def find_verb(self, verb_name: str, database=None):
        """
        Find a verb by name, checking this object and parents.

        Resolution only. Whether a *player* may reach what this returns
        is a dispatch question -- see ``moo.parser.may_invoke``, which
        weighs ``hidden`` and ``auth`` together at the two places a typed
        command is resolved.

        The ``hidden`` filter used to live here, which made it mean
        "unreachable by anything at all": every internal caller shares
        this method, so marking a hook hidden broke whatever called it.
        Hiding ``rlook`` cost staff the builder view for exactly that
        reason. Policy in a resolution primitive also has to be
        remembered by every caller, and the one that forgets fails
        silently -- which is the shape of most of the bugs this engine
        has had.
        
        Supports min-length prefix matching.  If a verb has
        ``min_lengths={'examine': 3}``, then 'exa', 'exam', etc.
        will match.
        
        Uses the flattened inheritance cache for O(1) lookups when
        available (prefixes are expanded into the cache).
        
        Args:
            verb_name: Verb name to find
            database: Database for parent resolution
            
        Returns:
            Tuple of (object_number, verb_def) or (None, None) if not found
        """
        # The cache first, because it is the O(1) one.
        #
        # This used to scan self.verbs linearly, calling matches() on each,
        # and only consult the cache when that missed -- so the cost of a
        # lookup was proportional to how many verbs the object itself
        # defines, and it was paid on every miss as well as every hit.
        # Measured on the shipped world: find_verb('msg') costs 174ns on an
        # object with no local verbs and 8,819ns on #3 Base_Character,
        # which has 78 -- and #3 is where every staff command lives, while
        # msg is the most-called verb in the game by an order of magnitude.
        #
        # Safe because the cache is a complete index rather than a
        # shortcut: _build_inheritance_cache walks root->self, so a local
        # verb already overrides an ancestor's, and matchable_names()
        # generates exactly the set matches() accepts -- checked against
        # all 212 verbs of the starter world, zero disagreements.  The
        # linear scan stays as the fallback for when no cache can be
        # built, which is the only case it was ever needed for.
        db = database or self._database
        self._ensure_cache(db)
        if self._inheritance_cache_valid and self._resolved_verbs is not None:
            hit = self._resolved_verbs.get(verb_name)
            if hit is not None:
                verb_def, defining_objnum = hit
                return (defining_objnum, verb_def)
            return (None, None)

        # No usable cache -- fall back to scanning what this object has.
        for verb in self.verbs:
            if verb.matches(verb_name):
                return (self.objnum, verb)

        return (None, None)
        
    def verbs_list(self, include_inherited: bool = True, database=None) -> List[str]:
        """
        Get list of verb names on this object.
        
        Args:
            include_inherited: Include verbs from parent chain
            database: Database for parent resolution
            
        Returns:
            List of verb names
        """
        if not include_inherited:
            verb_names = []
            for verb in self.verbs:
                verb_names.extend(verb.names)
            return verb_names
        
        # Use flattened inheritance cache for the full list
        db = database or self._database
        self._ensure_cache(db)
        if self._resolved_verbs is not None:
            return list(self._resolved_verbs.keys())
        
        # Fallback: local only
        verb_names = []
        for verb in self.verbs:
            verb_names.extend(verb.names)
        return verb_names
        
    # ========================================================================
    # LOCATION MANAGEMENT
    # ========================================================================
    
    def move_to(self, new_location, database):
        """
        Move this object to a new location.
        
        This handles updating both the old and new location's contents,
        as well as updating this object's location pointer.
        
        Args:
            new_location: Object number (int) or MOOObject of new location (0 = nowhere)
            database: Database for object resolution
            
        Raises:
            ValueError: If move would create a location loop
        """
        # Normalize: accept MOOObject or int
        if hasattr(new_location, 'objnum'):
            new_location = new_location.objnum
        # Check for location loops (can't move object inside itself or descendants)
        if new_location != 0:
            check_loc = new_location
            while check_loc != 0:
                if check_loc == self.objnum:
                    raise ValueError(
                        f"Cannot move #{self.objnum} to #{new_location}: "
                        "would create location loop"
                    )
                try:
                    check_obj = database.get_object(check_loc)
                    check_loc = check_obj._location_id
                except Exception:
                    break
                    
        # Remove from old location
        if self._location_id != 0:
            try:
                old_loc = database.get_object(self._location_id)
                if self.objnum in old_loc._content_ids:
                    old_loc._content_ids.remove(self.objnum)
                old_loc._mark_modified()
            except Exception:
                pass

        # Add to new location
        if new_location != 0:
            try:
                new_loc = database.get_object(new_location)
                if self.objnum not in new_loc._content_ids:
                    new_loc._content_ids.append(self.objnum)
                new_loc._mark_modified()
            except Exception:
                pass

        self._location_id = new_location
        self.last_move = time.time()
        self._mark_modified()
        logger.debug(f"Moved #{self.objnum} to #{new_location}")
        
    # ========================================================================
    # PARENT/CHILD MANAGEMENT
    # ========================================================================
    
    def change_parent(self, new_parent, database):
        """
        Change this object's parent.
        
        This updates the parent/child relationships and may affect
        property/verb inheritance.
        
        Args:
            new_parent: New parent object number (int) or MOOObject (0 = no parent)
            database: Database for object resolution
            
        Raises:
            ValueError: If new parent would create inheritance loop
            PermissionError: If new parent is not fertile
        """
        # Normalize: accept MOOObject or int
        if hasattr(new_parent, 'objnum'):
            new_parent = new_parent.objnum

        # Check for inheritance loops
        if new_parent != 0:
            check_parent = new_parent
            while check_parent != 0:
                if check_parent == self.objnum:
                    raise ValueError(
                        f"Cannot set parent to #{new_parent}: "
                        "would create inheritance loop"
                    )
                try:
                    check_obj = database.get_object(check_parent)
                    check_parent = check_obj.parent
                except Exception:
                    break
                    
        # Check if new parent is fertile
        if new_parent != 0:
            try:
                parent_obj = database.get_object(new_parent)
                if not parent_obj.is_fertile:
                    raise PermissionError(
                        f"Object #{new_parent} is not fertile"
                    )
            except PermissionError:
                raise
            except KeyError:
                pass

        # Remove from old parent's children
        old_parent_num = self.__dict__.get('parent', 0)
        if old_parent_num and old_parent_num != 0:
            try:
                old_parent_obj = database.get_object(old_parent_num)
                old_parent_obj.children.discard(self.objnum)
                database.save_object(old_parent_obj)
                logger.debug(f"Removed #{self.objnum} from #{old_parent_num}.children")
            except KeyError:
                logger.warning(f"Old parent #{old_parent_num} not found for #{self.objnum}")

        # Add to new parent's children
        if new_parent != 0:
            try:
                new_parent_obj = database.get_object(new_parent)
                new_parent_obj.children.add(self.objnum)
                database.save_object(new_parent_obj)
                logger.debug(f"Added #{self.objnum} to #{new_parent}.children")
            except KeyError:
                logger.warning(f"New parent #{new_parent} not found for #{self.objnum}")

        # Set parent directly, bypassing __setattr__ handler to avoid double-update
        object.__setattr__(self, 'parent', new_parent)
        self.invalidate_inheritance_cache(database)
        self._mark_modified()
        logger.debug(f"Changed parent of #{self.objnum} to #{new_parent}")
        
    # ========================================================================
    # SERIALIZATION
    # ========================================================================
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize this object to a plain dictionary for database storage.

        All live MOOObject references in property values are converted
        to their serialisable forms (``'#N'`` strings or integer objnums)
        by ``_store_objref()``.  ``_NullAttr`` sentinels are converted to
        ``None``.

        Returns:
            dict: A JSON-compatible dictionary containing all persistent
            state.  The returned dict is independent of the live object
            and safe to mutate.

        Notes:
            Transient/internal state (``_database``, ``_resolved_*``,
            ``_inheritance_cache_valid``, etc.) is intentionally omitted
            because it is rebuilt at load time.
        """
        return {
            'objnum': self.objnum,
            'parent': self.parent,
            'children': list(self.children),
            'noun': self.noun,
            'aliases': self.aliases,
            'owner': self.owner,
            'location': self._location_id,
            'contents': list(self._content_ids),
            'flags': self.flags,
            'properties': {
                name: {
                    'value': None if isinstance(prop.value, _NullAttr) else self._store_objref(prop.value),
                    'owner': prop.owner,
                    'perms': prop.perms
                }
                for name, prop in self.properties.items()
            },
            'verbs': [verb.to_dict() for verb in self.verbs],
            'created': self.created,
            'last_move': self.last_move,
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MOOObject':
        """
        Reconstruct a MOOObject from a serialised dictionary.

        This is the inverse of ``to_dict()``.  It handles several
        backward-compatibility concerns:

        * Old databases stored ``'name'`` instead of ``'noun'``.
        * Old databases stored a ``'player'`` integer field instead of
          using the PLAYER flag.

        The returned object has no database reference (``_database`` is
        ``None``) and its inheritance cache is not built.  The caller
        (typically the database layer) is responsible for attaching the
        database reference and triggering a cache build.

        Args:
            data (dict): Object data dictionary as produced by ``to_dict()``.

        Returns:
            MOOObject: A fully-populated but unattached object instance.
        """
        obj = cls(
            objnum=data['objnum'],
            parent=data.get('parent', 0),
            owner=data.get('owner', 0)
        )

        obj.children = set(data.get('children', []))
        # Backward compat: old databases have 'name', new ones have 'noun'
        obj.noun = data.get('noun', data.get('name', f"Object #{obj.objnum}"))
        obj.aliases = data.get('aliases', [])
        obj._location_id = data.get('location', 0)
        obj._content_ids = list(data.get('contents', []))
        obj.flags = data.get('flags', 0)
        # Backward compat: migrate old 'player' field into PLAYER flag
        if data.get('player', 0) and not obj.has_flag(ObjectFlags.PLAYER):
            obj.set_flag(ObjectFlags.PLAYER)
        obj.created = data.get('created', time.time())
        obj.last_move = data.get('last_move', obj.created)

        # Restore properties -- each becomes a PropertyInfo dataclass
        for name, prop_data in data.get('properties', {}).items():
            obj.properties[name] = PropertyInfo(
                name=name,
                value=prop_data.get('value'),
                owner=prop_data.get('owner', 0),
                perms=prop_data.get('perms', 'rc')
            )

        # Restore verbs -- each becomes a VerbDef (compiled lazily)
        from .verbs import VerbDef
        obj.verbs = [VerbDef.from_dict(v) for v in data.get('verbs', [])]

        return obj


# ---------------------------------------------------------------------------
# Bulk loading
# ---------------------------------------------------------------------------
#
# invalidate_inheritance_cache() walks every descendant, which is right for
# a live game: change a property on a generic parent and each child holding
# a resolved copy has to be told.  During a bulk load it is quadratic, and
# ruinously so -- an import of Inferno writes 483,851 properties into a tree
# of 60,967 objects mostly descending from a handful of parents, so each
# write sweeps most of the database.  Measured at 1,500 objects: 2.36
# million invalidation calls, and the full import took 72 minutes.
#
# Nothing is *reading* resolved values while a world is being built, so the
# sweeps have nobody to correct.  This defers them, and one pass at the end
# does the job all of them together would have.

_BULK_LOAD = False


@contextmanager
def bulk_load(db=None):
    """
    Defer inheritance-cache propagation for the duration.

    Use for building or importing a world, never for anything a player can
    reach: inside the block a child may serve a resolved value its parent
    has since changed.

    On exit every object in memory is invalidated once, which is what the
    deferred sweeps would have added up to.

    Args:
        db: The database to sweep on the way out.  Optional; without it the
            caller is responsible for invalidating.
    """
    global _BULK_LOAD
    was, _BULK_LOAD = _BULK_LOAD, True
    try:
        yield
    finally:
        _BULK_LOAD = was
        if db is not None and not _BULK_LOAD:
            for obj in list((getattr(db, '_objects', None) or {}).values()):
                obj._inheritance_cache_valid = False
                obj._resolved_properties = None
                obj._resolved_verbs = None
                obj._cache_dirty = True
