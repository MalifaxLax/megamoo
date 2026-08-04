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
import time

logger = logging.getLogger('megamoo.objects')


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
        
        Args:
            player_objnum: Player's object number
            player_wizard: Whether player is a wizard
            
        Returns:
            bool: True if player can write
        """
        if player_wizard:
            return True
        if player_objnum == self.owner:
            return self.is_writable
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

    Ordering is where the forgiveness stops, and that edge has one trap
    worth knowing.  ``max()`` and ``min()`` *return one of their
    arguments* rather than computing a new value, so::

        max(pobj.no_such_prop, 0)   # -> the sentinel, not 0

    The comparison inside ``max`` is right -- the sentinel orders as zero
    -- but the value handed back is still the sentinel, which then
    travels on and raises somewhere else entirely.  Write
    ``max(pobj.prop or 0, 0)`` when the result is used as a number.
    Arithmetic dunders are deliberately *not* defined: a missing property
    inside a sum is usually a misspelled property name, and that should
    fail loudly at the point of the mistake rather than quietly read as
    zero.

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

    def _resolve_objref(self, value):
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

    def msg_room(self, message: str, exclude=None, **kwargs):
        """
        Send *message* to all players in this object's contents.

        Works like the builtin ``msg_room()`` but as a method, so verb
        code can write ``pobj.location.msg_room(...)`` naturally.

        Each recipient is messaged through its own ``msg`` verb, so any
        per-object override of ``msg`` applies to room broadcasts too.

        Args:
            message: Message text (supports %S/%d/%i emit substitution and
                %0/%1/... raw-string slots).
            exclude: List of objects to exclude from receiving the message.
            **kwargs: Optional sub, dob, iob, uob for emit substitution, plus
                s0/s1/... raw-string slots (%N).
        """
        exclude_nums = set()
        for obj in (exclude or []):
            exclude_nums.add(obj.objnum if hasattr(obj, 'objnum') else obj)

        sub = kwargs.get('sub')
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
                return self._resolve_objref(props[name].value)

            # Check the flattened inheritance cache
            if self.__dict__.get('_inheritance_cache_valid') and self.__dict__.get('_resolved_properties'):
                resolved = self.__dict__['_resolved_properties']
                if name in resolved:
                    prop_info, _defining_objnum = resolved[name]
                    return self._resolve_objref(prop_info.value)
            else:
                # Try to build cache if we have a database reference
                db = self.__dict__.get('_database')
                if db:
                    self._ensure_cache(db)
                    resolved = self.__dict__.get('_resolved_properties')
                    if resolved and name in resolved:
                        prop_info, _defining_objnum = resolved[name]
                        return self._resolve_objref(prop_info.value)
        
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
        # Missing MOO property — return _null_attr (falsy, safely callable)
        return _null_attr
    
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
            props[name].value = value
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
            self.add_property(name, value=value, perms=inherited_info.perms)
            return

        # Brand-new property — check that the caller owns this object
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
    
    def _mark_modified(self):
        """
        Central mutation hook: invalidate caches and persist.

        Every method that mutates the object's state (property changes,
        moves, parent changes, etc.) calls this.  It:
        1. Invalidates the inheritance cache (and descendants).
        2. Auto-saves to the database if enabled.
        3. Sets ``_pending_save`` if auto-save is off, so a later
           explicit ``save()`` call knows work is pending.
        """
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
        border = f"%<245>{'=' * width}%n"
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

        # If property exists locally, set it
        if name in self.properties:
            self.properties[name].value = value
            self.invalidate_inheritance_cache()
            self._mark_modified()  # AUTO-SAVE
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
        # Fast path: check local verbs first
        for verb in self.verbs:
            if verb.matches(verb_name) and not verb.hidden:
                return (self.objnum, verb)

        # Use flattened inheritance cache
        db = database or self._database
        self._ensure_cache(db)
        if self._resolved_verbs is not None and verb_name in self._resolved_verbs:
            verb_def, defining_objnum = self._resolved_verbs[verb_name]
            if not verb_def.hidden:
                return (defining_objnum, verb_def)
                
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
