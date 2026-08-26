"""
MegaMOO Object Utilities

Pure-function library for common object creation and manipulation tasks.
No classes -- just functions that operate on MOO objects and the database.

This module is used primarily by builder and staff verbs (``@create``,
``@dig``, ``@room``, etc.) for creating rooms, items, exits, and other
game objects with proper setup of the name system and display titles.

Key concepts
------------

* **name_mod_list** -- A 5-element list that controls how an object's
  display name is constructed::

      [article, adj1, adj2, adj3, trailer]
      ['a',     'old', '',   '',   '']       -> "an old sword"
      ['the',   '',    '',   '',   '']       -> "the sword"
      ['',      '',    '',   '',   '(broken)'] -> "sword (broken)"

  The article is auto-corrected between "a" and "an" based on the
  first letter of the next word.

* **noun** -- The base noun of the object (e.g. "sword", "chest").
  Combined with name_mod_list to produce the full display name.

* **_title verb** -- A verb defined on parent objects that rebuilds
  ``obj.name`` from the noun and name_mod_list.  This module calls it
  after object creation, or falls back to inline title logic if no
  verb context is available.

  There is no stored capitalised name.  A ``cname`` property used to
  hold one, and being inheritable it was wrong more often than it was
  useful -- an object that never set its own answered with its
  prototype's.  ``&S``/``&D``/``&I`` capitalise ``name`` instead, and
  verb code that needs it calls ``su.capitalise(obj.name)``.

Architecture
------------

All functions in this module are stateless and operate on the objects
and database passed as arguments.  They do not import or depend on
server-level state, making them safe to use from bootstrap scripts,
migration tools, and verb code alike.

Copyright (c) 2026
License: MIT
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .objects import MOOObject
    from .database import Database


# =============================================================================
# Object Creation
# =============================================================================

def make_object(parent: 'MOOObject', db: 'Database', pobj: 'MOOObject',
                noun: Optional[str] = None,
                owner: Optional['MOOObject'] = None) -> 'MOOObject':
    """
    Create a new object as a child of *parent*.

    This is the primary factory function for creating game objects
    (items, NPCs, containers, etc.).  It handles:

    1. Creating the object in the database with proper parent/owner.
    2. Copying the ``name_mod_list`` from the parent (inherits article).
    3. Setting the noun (either the given *noun* or the parent's noun).
    4. Calling ``_title`` to build the display name.
    5. Firing the ``object_creation`` hook.

    If *noun* is given, it becomes the new object's noun and the
    ``name_mod_list`` is copied from the parent.  If *noun* is ``None``,
    both the noun and ``name_mod_list`` are copied from the parent
    unchanged.

    Args:
        parent: The parent object to inherit from (determines the
                object's type and default properties).
        db:     The database instance.
        pobj:   The player creating the object (verb execution context).
        noun:   Optional noun for the new object.  If omitted, the
                parent's noun and name_mod_list are used as-is.
        owner:  Optional owner object.  Defaults to *pobj*.

    Returns:
        The newly created MOOObject, with name and title fully set up.

    Examples::

        # Create a sword from the GenericItem parent (#11)
        sword = make_object(db.get_object(11), db, pobj, noun='sword')

        # Create a copy with the same name as the parent
        clone = make_object(db.get_object(11), db, pobj)

        # Create with a different owner
        gift = make_object(parent, db, pobj, noun='gift', owner=recipient)
    """
    owner_obj = owner or pobj
    new_obj = db.create_object(parent=parent.objnum, owner=owner_obj.objnum)

    # Copy name_mod_list from parent, defaulting to ['a', '', '', '', '']
    parent_nml = _get_property_value(parent, 'name_mod_list', db)
    if parent_nml is not None:
        nml = list(parent_nml)
    else:
        nml = ['a', '', '', '', '']

    # Set the noun -- either the provided noun or the parent's noun
    if noun is not None:
        new_obj.noun = noun
    else:
        new_obj.noun = parent.noun

    _set_property(new_obj, 'name_mod_list', nml)

    # Call _title to build the display name from noun + name_mod_list
    _call_title(new_obj, db, pobj)

    # Fire the object_creation hook
    from .hooks import fire_hook
    fire_hook('object_creation', new_obj)

    return new_obj


# Import room type mappings from globals (canonical source of truth)


def make_room(parent: 'MOOObject', db: 'Database', pobj: 'MOOObject',
              name: Optional[str] = None) -> 'MOOObject':
    """
    Create a new room as a child of *parent*.

    Rooms are simpler than regular objects: they don't use the
    name_mod_list system.  The room name is set directly as both
    the ``noun`` and ``name`` properties.

    Room parent objects are defined in ``globals.py``:

    ===========  =======  ==================
    Type key     ObjNum   Description
    ===========  =======  ==================
    ``'room'``   #15      BaseRoom
    ``'ooc'``    #16      OOCRoom (out-of-character)
    ``'ic'``     #17      ICRoom (in-character)
    ===========  =======  ==================

    Args:
        parent: The room-type parent to inherit from (e.g. #15, #16, #17).
        db:     The database instance.
        pobj:   The player creating the room (becomes the owner).
        name:   Optional name for the room.  If omitted, the parent's
                noun is used as a default.

    Returns:
        The newly created room MOOObject.

    Examples::

        # Create an IC room named "Town Square"
        room = make_room(db.get_object(17), db, pobj, name='Town Square')

        # Create an OOC room with the default name from the parent
        lounge = make_room(db.get_object(16), db, pobj)
    """
    room_name = name if name else parent.noun
    new_room = make_object(parent, db, pobj, noun=room_name)
    new_room.name = room_name
    return new_room


def make_exit(parent: 'MOOObject', db: 'Database', pobj: 'MOOObject',
              noun: Optional[str] = None,
              room: Optional['MOOObject'] = None,
              dest: Optional['MOOObject'] = None,
              fname: Optional[str] = None,
              rfname: Optional[str] = None) -> 'MOOObject':
    """
    Create a new exit as a child of *parent* and place it in *room*.

    Handles:
    1. Creating the exit object via make_object.
    2. Setting the destination property.
    3. Moving the exit into the room and adding it to the room's exits list.
    4. Setting default success/osuccess/odrop messages using fname/rfname.

    Args:
        parent: The exit parent object (#20, #21, #22, #23, etc.).
        db:     The database instance.
        pobj:   The player creating the exit.
        noun:   The exit's noun (e.g. 'north', 'door', 'gate').
        room:   The room to place the exit in.
        dest:   Optional destination room.
        fname:  Full direction name for messages (e.g. 'north'). Defaults to noun.
        rfname: Reverse full name for arrival messages (e.g. 'the south'). Defaults to fname.

    Returns:
        The newly created exit MOOObject.
    """
    new_exit = make_object(parent, db, pobj, noun=noun)

    # Movement messages, naming the direction this exit actually goes.
    #
    # Step 4 of the list above, which the body did not do.  Every exit
    # therefore inherited #20 BaseExit's literals -- "You walk out." going
    # north, south and every other way -- and an osuccess still written in
    # the %% sigil from before it moved to &, so the watching room got
    # "%%S %%OMODE out." on every move through a created exit.
    #
    # The templates have been in globals.py as ESUCC/EOSUCC/EODROP all
    # along; `&1` is the slot fname and rfname exist to fill.
    #
    # Only when there is a name to put in.  A go-exit created without one
    # keeps whatever its parent says, which is right for `go archway`:
    # there is no direction to announce.
    _fname = fname or noun
    if _fname:
        from .globals import ESUCC, EOSUCC, EODROP, GESUCC, GEOSUCC
        _rfname = rfname or _fname
        if fname:
            # A direction was named, so the name belongs in the sentence:
            # you go north, you do not go through north.
            _succ, _osucc = (ESUCC.replace('&1', _fname),
                             EOSUCC.replace('&1', _fname))
        else:
            # A named exit -- a door, an archway, drapes -- is a thing you
            # go through, and &d reads its name at emit time so a later
            # rename carries.  Only @open names a direction; the four
            # named-exit builders pass none, which is what tells them
            # apart here without make_exit having to know their parents.
            _succ, _osucc = GESUCC, GEOSUCC
        new_exit.add_property('success', _succ, perms='rc')
        new_exit.add_property('osuccess', _osucc, perms='rc')
        new_exit.add_property('odrop', EODROP.replace('&1', _rfname), perms='rc')

    # Set destination
    if dest:
        new_exit.add_property('destination', dest.objnum, perms='rc')

    # Place in room
    if room:
        new_exit.move_to(room, db)
        exits = room.exits or []
        exits.append(new_exit.objnum)
        room.exits = exits
        room._mark_modified()

    return new_exit


# =============================================================================
# Exit Utilities
# =============================================================================

def order_exits(exits: list) -> list:
    """
    Sort exits by DNAMES order.

    Accepts a mixed list of exit name strings, direction index ints,
    or exit objects (with a ``noun`` attribute).  Directional exits are
    sorted in canonical compass order; non-directional exits are
    appended after in their original order.

    Args:
        exits: List of exit name strings, ints, or exit objects.

    Returns:
        Sorted list (same element types as input).
    """
    from .globals import DNAMES

    def _key(o):
        if isinstance(o, int):
            return o
        name = getattr(o, 'noun', None) or (o if isinstance(o, str) else '')
        return DNAMES.index(name) if name in DNAMES else 99

    return sorted(exits, key=_key)


# =============================================================================
# Internal Helpers -- Property Access
# =============================================================================

def _get_property_value(obj: 'MOOObject', prop_name: str, db: 'Database' = None):
    """
    Get a property value from *obj*, walking the inheritance chain.

    Checks the object's local properties first.  If the property is not
    found locally, walks up the parent chain (using the database to
    resolve parent object numbers) until the property is found or the
    chain is exhausted.

    Circular parent references are detected and avoided via a visited
    set.

    Args:
        obj:       The object to read the property from.
        prop_name: Name of the property to look up.
        db:        Database instance for resolving parent objects.
                   If ``None``, attempts to get the database from the
                   active verb context.

    Returns:
        The property value, or ``None`` if not found anywhere in the
        inheritance chain.
    """
    # Check local properties first (fast path)
    if prop_name in obj.properties:
        return obj.properties[prop_name].value

    # If no database was provided, try to get one from the verb context
    if db is None:
        try:
            from .verb_context import verb_ctx
            ctx = verb_ctx.get(None)
            if ctx:
                db = ctx[1]
        except Exception:
            pass

    # Walk the parent chain looking for an inherited property
    if db is not None:
        parent_num = obj.parent
        visited = {obj.objnum}  # Track visited objects to prevent cycles
        while parent_num and parent_num not in visited:
            visited.add(parent_num)
            try:
                parent_obj = db.get_object(parent_num)
            except (KeyError, Exception):
                break
            if prop_name in parent_obj.properties:
                return parent_obj.properties[prop_name].value
            parent_num = parent_obj.parent

    return None


def _set_property(obj: 'MOOObject', prop_name: str, value):
    """
    Set a property on *obj*, creating it if it does not exist locally.

    If the property already exists on the object, its value is updated
    in place.  Otherwise, a new property is added with default
    permissions ``'rc'`` (readable, inheritable).

    The object is marked as modified after the change so it will be
    saved to the database on the next save cycle.

    Args:
        obj:       The object to set the property on.
        prop_name: Name of the property.
        value:     The value to set (any Python type).
    """
    if prop_name in obj.properties:
        obj.properties[prop_name].value = value
    else:
        obj.add_property(prop_name, value, perms='rc')
    obj._mark_modified()


# =============================================================================
# Internal Helpers -- Title Construction
# =============================================================================

def _call_title(obj: 'MOOObject', db: 'Database', pobj: 'MOOObject'):
    """
    Call the ``_title`` verb on *obj* to rebuild its display name.

    The ``_title`` verb constructs ``obj.name`` from the object's noun
    and name_mod_list.  This function first tries to
    invoke ``_title`` via the verb execution system (using ``call_verb``
    from the active verb context).  If no verb context is available
    (e.g. during bootstrap or direct script calls), it falls back to
    :func:`_inline_title` which implements the same logic directly.

    Args:
        obj:  The object whose title needs to be rebuilt.
        db:   The database instance.
        pobj: The player object (needed for verb execution context).
    """
    try:
        from .verb_context import verb_ctx
        ctx = verb_ctx.get(None)
        if ctx:
            from .builtins import make_call_verb
            call_verb = make_call_verb(pobj, db, ctx[2])
            call_verb(obj, '_title')
            return
    except Exception:
        pass

    # Fallback: inline the _title logic if no verb context is available
    _inline_title(obj)


def _inline_title(obj: 'MOOObject'):
    """
    Inline fallback for ``_title`` when no verb execution context
    is available (e.g. during bootstrap, migration, or direct script
    calls).

    Builds the display name from the object's noun and name_mod_list:

    1. Reads name_mod_list: ``[article, adj1, adj2, adj3, trailer]``
    2. Auto-corrects "a"/"an" based on the first letter of the next word
    3. Joins non-empty parts with spaces
    4. Appends the trailer (e.g. "(broken)") if present
    5. Sets ``obj.name`` and updates name_mod_list

    Args:
        obj: The object whose title needs to be rebuilt.
    """
    # Read the name_mod_list from local properties
    nml_val = None
    if 'name_mod_list' in obj.properties:
        nml_val = obj.properties['name_mod_list'].value

    # Ensure nml is always a 5-element list
    if nml_val:
        nml = list(nml_val)
        while len(nml) < 5:
            nml.append('')
    else:
        nml = ['', '', '', '', '']

    # Decompose the name_mod_list
    article = (nml[0] or '').strip()
    adjs = [a.strip() for a in nml[1:4] if a and a.strip()]
    trailer = (nml[4] or '').strip()
    noun = (obj.noun or '').strip()

    # Auto-correct a/an based on the first letter of the next word
    if article.lower() in ('a', 'an'):
        first_word = adjs[0] if adjs else noun
        if first_word and first_word[0].lower() in 'aeiou':
            article = 'an' if article[0].islower() else 'An'
        else:
            article = 'a' if article[0].islower() else 'A'
        nml[0] = article

    # Build the display name: "a rusty old sword"
    parts = [p for p in [article] + adjs + [noun] if p]
    name = ' '.join(parts)
    if trailer:
        name = f'{name} {trailer}'

    # Update the object
    obj.name = name
    _set_property(obj, 'name_mod_list', nml)


# ===========================================================================
# LambdaMOO $object_utils compatibility
#
# The five methods below are 85% of $object_utils' use across JHCore, added
# so code brought over by @port has somewhere to land.  Written from
# JHCore's own definitions (#47, "object utilities"); each docstring quotes
# the original.
# ===========================================================================

def ancestors(*objs):
    """
    Every ancestor of the given object(s), nearest first, without duplicates.

    JHCore: "Return a list of all ancestors of the object(s) in args, with
    no duplicates.  If called with a single object, the result will be in
    order ascending up the inheritance hierarchy."  The object itself is
    not included.
    """
    out = []
    for obj in objs:
        node = _parent_of(obj)
        seen = set()
        while node is not None and getattr(node, 'objnum', None) not in seen:
            seen.add(node.objnum)
            if node not in out:
                out.append(node)
            node = _parent_of(node)
    return out


def _parent_of(obj):
    """The parent as a live object, or None.  Parents may be stored as ints."""
    from .builtins import _database
    parent = getattr(obj, 'parent', None)
    if not parent:
        return None
    if isinstance(parent, int):
        if parent <= 0:
            return None
        try:
            return _database.get_object(parent)
        except Exception:
            return None
    return parent


def isa(what, targ) -> bool:
    """
    Whether *what* is *targ* or descends from it.

    JHCore: ":isa(x,y) == valid(x) && (y==x || y in :ancestors(x))".  Walks
    the parent chain, with a guard against a cycle in a damaged database.
    """
    if what is None or targ is None:
        return False
    want = getattr(targ, 'objnum', targ)
    node, seen = what, set()
    while node is not None:
        num = getattr(node, 'objnum', None)
        if num == want:
            return True
        if num in seen:
            return False
        seen.add(num)
        node = _parent_of(node)
    return False


def has_verb(obj, name: str) -> bool:
    """Whether *obj* or an ancestor defines a verb called *name*."""
    node = obj
    seen = set()
    while node is not None and getattr(node, 'objnum', None) not in seen:
        seen.add(node.objnum)
        try:
            for v in node.verbs or []:
                if name in (v.names or []):
                    return True
        except Exception:
            pass
        node = _parent_of(node)
    return False


def has_callable_verb(obj, name: str) -> bool:
    """
    As has_verb, but only counting verbs that can actually be called.

    A verb without the execute permission is defined but not callable, and
    JHCore distinguishes the two.
    """
    node = obj
    seen = set()
    while node is not None and getattr(node, 'objnum', None) not in seen:
        seen.add(node.objnum)
        try:
            for v in node.verbs or []:
                if name in (v.names or []) and 'x' in (v.perms or ''):
                    return True
        except Exception:
            pass
        node = _parent_of(node)
    return False


def has_property(obj, name: str) -> bool:
    """
    Whether *obj* has the named property, inherited or its own.

    A missing property reads back as the falsy sentinel rather than
    raising, so the test is against that rather than against an exception.
    """
    if obj is None or not name:
        return False
    try:
        return getattr(obj, name) != None      # noqa: E711 -- sentinel
    except AttributeError:
        return False


def all_properties(obj) -> list:
    """
    Every property name defined on *obj* or any of its ancestors.

    MOO's ``$object_utils:all_properties``, which its cores use wherever
    something has to touch an object's whole property surface -- chowning
    it, listing its messages, gathering help topics.  MegaMOO had no way to
    ask, and the question is a fair one.

    Nearest first: the object's own definitions, then up the chain.  A name
    redefined further down appears once, at the point that wins.

    Args:
        obj: The object.

    Returns:
        list: Property names, without duplicates.
    """
    out, seen = [], set()
    for node in (obj,) + tuple(ancestors(obj)):
        for name in (getattr(node, 'properties', None) or ()):
            if name not in seen:
                seen.add(name)
                out.append(name)
    return out


def all_verbs(obj) -> list:
    """
    Every verb name defined on *obj* or any of its ancestors.

    The companion to :func:`all_properties`, and the same shape: nearest
    first, no duplicates.  A verb with several names contributes each of
    them, since any of them is what a caller would use.

    Args:
        obj: The object.

    Returns:
        list: Verb names, without duplicates.
    """
    out, seen = [], set()
    for node in (obj,) + tuple(ancestors(obj)):
        for verb in (getattr(node, 'verbs', None) or ()):
            names = getattr(verb, 'names', None) or []
            for name in ([names] if isinstance(names, str) else names):
                if name not in seen:
                    seen.add(name)
                    out.append(name)
    return out


def system_ref(db, name, fallback_objnum=None):
    """
    Resolve a ``$ref`` -- a property on #0 -- to whatever it holds.

    The engine used to reach for object numbers directly: the verb tree's
    location was on #8, player storage was #2, and both were written into
    the code.  That made those two numbers part of the engine's contract
    with every database, which is a strange thing for an engine to require
    when it already has a perfectly good name-to-object mechanism.

    Now they are ``$refs`` like everything else, which means a minimal
    database is #0 and #1 and nothing more.

    Args:
        db: The database.
        name: The property name on #0.
        fallback_objnum: Where to look if #0 does not define it.  This is
            how databases built before the move keep working: they have the
            object at its old number and no $ref pointing at it.

    Returns:
        The value, or None.
    """
    try:
        zero = db.get_object(0)
    except Exception:
        zero = None
    value = getattr(zero, name, None) if zero is not None else None
    if value is not None and repr(value) != 'None':
        return value
    if fallback_objnum is None:
        return None
    try:
        return db.get_object(fallback_objnum)
    except Exception:
        return None


def descendants(obj) -> list:
    """
    Every object below *obj* in the inheritance tree, breadth-first.

    The counterpart to :func:`ancestors`, and the question `@kids` answers
    one level at a time.  MOO's cores reach for it whenever something has
    to apply to a whole family -- rechowning a hierarchy, finding what
    would break if a property changed.

    ``children`` holds object *numbers*, not objects.  This used to read
    ``getattr(node, 'objnum', None)`` and skip the node when it came back
    None -- which, for an int, it always did.  So every descendant was
    dropped and the answer was ``[]``, for every object in the world, without
    raising.  ``leaves()`` is built on this and was empty for the same
    reason, and ``moo verbs/50/_td_dump.py`` carries a hand-written copy of
    this function with the resolving line in it, which is how long the engine
    version has been wrong.

    Resolution is per node and tolerant: a number naming an object that has
    been recycled is skipped rather than raising, because a stale entry in
    ``children`` is a thing that happens and is not this function's to fix.

    Args:
        obj: The object.

    Returns:
        list: Descendants, nearest generation first, without duplicates.
    """
    db = getattr(obj, '_database', None)

    def _resolve(entry):
        if hasattr(entry, 'objnum'):
            return entry
        if db is None:
            return None
        try:
            return db.get_object(int(entry))
        except Exception:
            return None

    out, seen, queue = [], set(), list(getattr(obj, 'children', None) or ())
    while queue:
        node = _resolve(queue.pop(0))
        if node is None:
            continue
        num = getattr(node, 'objnum', None)
        if num is None or num in seen:
            continue
        seen.add(num)
        out.append(node)
        queue.extend(getattr(node, 'children', None) or ())
    return out


def leaves(obj) -> list:
    """
    The descendants of *obj* that have no children of their own.

    In a MOO hierarchy these are the things somebody actually made, as
    against the generic parents they were made from -- so "every real
    room" is ``leaves($room)``.

    Args:
        obj: The object.

    Returns:
        list: Childless descendants.
    """
    return [o for o in descendants(obj)
            if not (getattr(o, 'children', None) or ())]


def all_contents(obj) -> list:
    """
    Everything inside *obj*, and inside those things, all the way down.

    Args:
        obj: The container, room or character.

    Returns:
        list: Contents, recursively, without duplicates.
    """
    out, seen, queue = [], set(), list(getattr(obj, 'contents', None) or ())
    while queue:
        node = queue.pop(0)
        num = getattr(node, 'objnum', None)
        if num is None or num in seen:
            continue
        seen.add(num)
        out.append(node)
        queue.extend(getattr(node, 'contents', None) or ())
    return out


def contains(obj, thing) -> bool:
    """
    Whether *thing* is inside *obj*, at any depth.

    Args:
        obj: The container.
        thing: What to look for.

    Returns:
        bool: True if it is in there somewhere.
    """
    want = getattr(thing, 'objnum', thing)
    return any(getattr(o, 'objnum', None) == want for o in all_contents(obj))


def locations(obj) -> list:
    """
    Where *obj* is, and where that is, out to the outermost container.

    Args:
        obj: The object.

    Returns:
        list: Containing objects, innermost first.
    """
    out, seen = [], set()
    node = getattr(obj, 'location', None)
    while node is not None and getattr(node, 'objnum', None) not in seen:
        seen.add(node.objnum)
        out.append(node)
        node = getattr(node, 'location', None)
    return out


def defines_property(obj, name: str) -> bool:
    """
    Whether *obj* declares *name* itself, rather than inheriting it.

    The distinction :func:`has_property` does not make.  MOO's cores need
    it to tell "this object has its own description" from "this object
    shows its parent's".

    Args:
        obj: The object.
        name: Property name.

    Returns:
        bool: True if the definition is this object's own.
    """
    return name in (getattr(obj, 'properties', None) or {})


def defines_verb(obj, name: str) -> bool:
    """
    Whether *obj* carries a verb called *name* itself, not inherited.

    Args:
        obj: The object.
        name: Verb name.

    Returns:
        bool: True if the verb is defined here.
    """
    for verb in (getattr(obj, 'verbs', None) or ()):
        names = getattr(verb, 'names', None) or []
        if name in ([names] if isinstance(names, str) else names):
            return True
    return False


def login_room(db):
    """
    Where a player lands when they log in.

    Resolved as a ``$ref`` rather than an object number.  It used to be the
    constant ``LOGIN_ROOM = 14``, which is right for the shipped database
    and arbitrary everywhere else: in a world built from nothing, #14 is
    whatever happened to be created fourteenth -- in practice a pooled
    blank character, so logging in moved the player *into another player*
    and the first command failed with "look_here not found on
    PlayerPlace (#14)".

    Order: ``$login_room``, then ``$start_room``, then the old constant.
    A world that wants an out-of-character entry hall points $login_room at
    it; one that does not lands people wherever it starts.

    Args:
        db: The database.

    Returns:
        The room, or None if nothing sensible resolves -- in which case the
        caller should leave the player where they are rather than move them
        somewhere arbitrary.
    """
    from .object_utils import system_ref
    for ref in ('login_room', 'start_room'):
        room = system_ref(db, ref)
        if room is not None and repr(room) != 'None':
            return room
    # Last resort.  This used to be `globals.LOGIN_ROOM`, a Python constant
    # naming an object number -- which @renumber cannot maintain, so a world
    # that repacked its numbers left the engine pointing at whatever moved
    # into #14.  It is $globals.login_room now, which @renumber does maintain
    # because it is listed in $objref_props.
    holder = system_ref(db, 'globals')
    fallback = getattr(holder, 'login_room', None) if holder is not None else None
    if not isinstance(fallback, int):
        return None
    try:
        room = db.get_object(fallback)
    except Exception:
        return None
    # The constant is a guess about a database it may know nothing about,
    # so it has to be checked.  A player parked in another player is worse
    # than a player left standing where they were.
    return room if getattr(room, 'is_room', False) else None
