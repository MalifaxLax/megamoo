"""
MegaMOO Permission System
=========================

This module implements MegaMOO's permission and security model, controlling who
can read/write properties, execute verbs, and perform administrative tasks.
It is the authoritative gatekeeper for all object-level access in the server.

Conceptual Overview
-------------------
MegaMOO follows the classic LambdaMOO permission hierarchy.  Every object,
property, and verb has an *owner* (a player object number) and a set of
*permission bits* (read, write, execute, debug).  Access decisions combine the
caller's privilege level with the target's permission bits:

    Wizard (flag on player object)
        Full, unrestricted access to everything.  Wizards bypass all
        permission checks, quota limits, and object-ownership gates.

    Programmer (flag on player object)
        Can create and modify verb code.  Reading other players' verb code
        still requires the 'r' (READ) bit on the verb, but programmers have
        broader code-level access than ordinary players.

    Owner
        The player whose objnum matches the ``owner`` field of a property
        or verb has elevated access to that specific item (e.g. an owner
        can always read their own verb code).

    Everyone else
        Access is determined solely by the public permission bits on the
        property or verb.

Permission Bits
---------------
Stored as an integer bitmask and commonly represented as a human-readable
string such as ``"rwx"`` or ``"rd"``:

    r (READ)    -- 0x01 -- Can read the property value / verb code.
    w (WRITE)   -- 0x02 -- Can write (modify) the property value / verb code.
    x (EXECUTE) -- 0x04 -- Can call the verb.
    d (DEBUG)   -- 0x08 -- Can set breakpoints / inspect runtime state.

Architecture Notes
------------------
* :class:`PermissionChecker` was *intended* as the single point of truth for
  permission decisions.  It is not one, and this note used to say otherwise.
  Only ``can_execute_verb`` and ``can_read_property`` are called from
  anywhere, and ``can_execute_verb`` only from :class:`~moo.verbs.VerbExecutor`
  -- which the running server does not use, since player input goes through
  ``MegaMOOServer.execute_command`` instead.  The checks that actually run
  live in ``verb_namespace`` and ``objects``; the quota system runs nowhere
  at all.  Check what calls a method here before trusting it to be enforcing
  anything.
* The checker receives the ``Database`` at construction time so it can look
  up property/verb metadata without the caller needing to pass it each time.
* Quota management (``check_quota`` / ``deduct_quota``) is co-located here
  because it is conceptually part of "is this player allowed to do X?".

See Also
--------
* ``objects.py`` -- ``MOOObject`` and ``ObjectFlags`` definitions.
* ``verbs.py``   -- ``VerbDef`` (carries ``owner`` and ``perms`` fields).

Copyright (c) 2026
License: MIT
"""

from typing import Optional
from enum import IntEnum
import logging

from .objects import MOOObject, ObjectFlags

logger = logging.getLogger('megamoo.permissions')


# =============================================================================
# EXCEPTIONS
# =============================================================================

class PermissionError(Exception):
    """
    Raised when a permission check fails.

    Command handlers and verb execution code catch this to display an
    appropriate "Permission denied" message to the player.
    """
    pass


# =============================================================================
# PERMISSION BIT FLAGS
# =============================================================================

class Permission(IntEnum):
    """
    Permission bit flags for properties and verbs.

    These follow the classic MOO convention where each permission is a
    single bit in an integer bitmask, allowing them to be combined with
    bitwise OR.

    Attributes:
        READ:    0x01 -- Can read the property value or verb source code.
        WRITE:   0x02 -- Can modify the property value or verb source code.
        EXECUTE: 0x04 -- Can call/invoke the verb.
        DEBUG:   0x08 -- Can attach a debugger or inspect runtime state.

    Example::

        perms = Permission.READ | Permission.EXECUTE  # 5 == "rx"
    """
    READ = 1 << 0      # Can read property/verb
    WRITE = 1 << 1     # Can write property/verb
    EXECUTE = 1 << 2   # Can execute verb
    DEBUG = 1 << 3     # Can debug verb


# =============================================================================
# PERMISSION STRING CONVERSION
# =============================================================================

def parse_perms(perm_string: str) -> int:
    """
    Parse a human-readable permission string into a bitmask.

    Converts a short permission string (e.g. ``"rwx"``, ``"r"``, ``"rxd"``)
    into the corresponding integer of ORed :class:`Permission` flags.
    Character order does not matter; unknown characters are silently ignored.
    The comparison is case-insensitive.

    Args:
        perm_string (str): Permission string containing any combination of
            ``r`` (readable), ``w`` (writable), ``x`` (executable),
            ``d`` (debuggable).

    Returns:
        int: Combined permission bitmask.

    Examples::

        >>> parse_perms("rwx")
        7  # READ | WRITE | EXECUTE
        >>> parse_perms("rx")
        5  # READ | EXECUTE
        >>> parse_perms("d")
        8  # DEBUG only
        >>> parse_perms("")
        0  # no permissions
    """
    perms = 0

    if 'r' in perm_string.lower():
        perms |= Permission.READ
    if 'w' in perm_string.lower():
        perms |= Permission.WRITE
    if 'x' in perm_string.lower():
        perms |= Permission.EXECUTE
    if 'd' in perm_string.lower():
        perms |= Permission.DEBUG

    return perms


def format_perms(perms: int) -> str:
    """
    Format a permission bitmask as a human-readable string.

    This is the inverse of :func:`parse_perms`.  The letters always appear
    in canonical order: ``r``, ``w``, ``x``, ``d``.  If no bits are set
    the function returns ``"-"`` (the MOO convention for "no permissions").

    Args:
        perms (int): Permission bitmask (combination of :class:`Permission` flags).

    Returns:
        str: Permission string (e.g. ``"rwx"``, ``"r"``, ``"-"``).

    Examples::

        >>> format_perms(7)
        'rwx'
        >>> format_perms(Permission.READ)
        'r'
        >>> format_perms(0)
        '-'
    """
    result = ''

    if perms & Permission.READ:
        result += 'r'
    if perms & Permission.WRITE:
        result += 'w'
    if perms & Permission.EXECUTE:
        result += 'x'
    if perms & Permission.DEBUG:
        result += 'd'

    return result or '-'


# =============================================================================
# PERMISSION CHECKER
# =============================================================================

class PermissionChecker:
    """
    Centralised permission enforcement for all MOO operations.

    Every security-sensitive operation in MegaMOO (reading a property,
    executing a verb, creating or recycling an object, etc.) is routed
    through a method on this class.  This ensures that permission logic
    lives in a single, auditable location rather than being scattered
    across command handlers.

    The checker follows a consistent pattern for every method:

    1. **Wizard bypass** -- if the acting player has the ``WIZARD`` flag,
       access is granted unconditionally.
    2. **Ownership check** -- the owner of the target (property, verb, or
       object) often has elevated access.
    3. **Permission-bit check** -- the public permission bits (``r``, ``w``,
       ``x``, ``d``) determine access for non-owners.

    Attributes:
        database: The :class:`~moo.database.Database` instance used to look
            up objects and property metadata during permission checks.

    Usage::

        checker = PermissionChecker(database)
        if checker.can_read_property(player, target_obj, 'description'):
            value = target_obj.get_property('description', database)
        else:
            player.msg("Permission denied.")
    """

    def __init__(self, database):
        """
        Initialise the permission checker.

        Args:
            database: A :class:`~moo.database.Database` instance.  Stored
                as ``self.database`` and used for property-info lookups,
                quota reads/writes, and object retrieval.
        """
        self.database = database

    # -------------------------------------------------------------------------
    # Property access
    # -------------------------------------------------------------------------

    def can_read_property(self, player: MOOObject, obj: MOOObject,
                         prop_name: str) -> bool:
        """
        Determine whether *player* may read *prop_name* on *obj*.

        Permission rules (evaluated in order, first match wins):
            1. Wizards can read any property on any object.
            2. If the property's ``is_readable`` flag is set, anyone can read it.
            3. The property's *owner* can always read it (even if not publicly
               readable).
            4. Otherwise, access is denied.

        Args:
            player (MOOObject): The player attempting the read.
            obj (MOOObject):    The object that owns the property.
            prop_name (str):    The name of the property to read.

        Returns:
            bool: ``True`` if the player is allowed to read the property.
        """
        # Wizards can read anything
        if player.is_wizard:
            return True

        # Get property info
        try:
            prop_info = obj.get_property_info(prop_name, self.database)
        except KeyError:
            # Property does not exist -- nothing to read
            return False

        # Check if property is readable by anyone
        if prop_info.is_readable:
            return True

        # Owner can read their own properties
        if player.objnum == prop_info.owner:
            return True

        return False

    def can_write_property(self, player: MOOObject, obj: MOOObject,
                          prop_name: str) -> bool:
        """
        Determine whether *player* may write (modify) *prop_name* on *obj*.

        Permission rules (evaluated in order, first match wins):
            1. Wizards can write any property on any object.
            2. The property's *owner* can write it **only if** the property's
               ``is_writable`` flag is also set.
            3. Otherwise, access is denied.

        Note:
            Unlike reading, mere ownership is not sufficient -- the property
            must also carry the ``w`` permission bit.  This prevents
            accidental modification of critical internal properties even by
            their owner.

        Args:
            player (MOOObject): The player attempting the write.
            obj (MOOObject):    The object that owns the property.
            prop_name (str):    The name of the property to write.

        Returns:
            bool: ``True`` if the player is allowed to write the property.
        """
        # Wizards can write anything
        if player.is_wizard:
            return True

        # Get property info
        try:
            prop_info = obj.get_property_info(prop_name, self.database)
        except KeyError:
            # Property does not exist -- cannot write a non-existent property
            return False

        # Must be owner and property must be writable
        if player.objnum == prop_info.owner and prop_info.is_writable:
            return True

        return False

    # -------------------------------------------------------------------------
    # Verb access
    # -------------------------------------------------------------------------

    def can_execute_verb(self, player: MOOObject, verb_obj: MOOObject,
                        verb_def) -> bool:
        """
        Determine whether *player* may execute a verb.

        Permission rules (evaluated in order, first match wins):
            1. Wizards can execute any verb.
            2. If the verb lacks the ``x`` (EXECUTE) permission bit, only the
               verb's *owner* may call it.
            3. If the verb has the ``x`` bit set (or has no ``perms`` attribute
               at all -- the permissive default), anyone may call it.

        Args:
            player (MOOObject):  The player attempting to run the verb.
            verb_obj (MOOObject): The object the verb is defined on.
            verb_def:            The :class:`~moo.verbs.VerbDef` instance.  Must
                                 have ``perms`` (str) and ``owner`` (int) attrs.

        Returns:
            bool: ``True`` if the player is allowed to execute the verb.
        """
        # Wizards can execute anything
        if player.is_wizard:
            return True

        # Check verb permissions
        if hasattr(verb_def, 'perms'):
            perms = parse_perms(verb_def.perms)
            if not (perms & Permission.EXECUTE):
                # Verb is not publicly executable --
                # but the owner can always execute their own verbs.
                if player.objnum == verb_def.owner:
                    return True
                return False

        # Verb is executable (or has no perms attribute -- permissive default)
        return True

    def can_read_verb_code(self, player: MOOObject, verb_obj: MOOObject,
                          verb_def) -> bool:
        """
        Determine whether *player* may read (view) the source code of a verb.

        This controls commands like ``@list`` and the verb-editor's "open"
        action.

        Permission rules (evaluated in order, first match wins):
            1. Wizards can read any verb source.
            2. Programmers can read the source **only if** the verb's ``r``
               (READ) permission bit is set.
            3. The verb's *owner* can always read their own code.
            4. Otherwise, access is denied.

        Note:
            Non-programmer players can never read verb code, even if the
            verb is marked readable -- the ``is_programmer`` gate ensures
            that only coding-capable players access source.

        Args:
            player (MOOObject):  The player attempting to read code.
            verb_obj (MOOObject): The object the verb is defined on.
            verb_def:            The :class:`~moo.verbs.VerbDef` instance.

        Returns:
            bool: ``True`` if the player is allowed to view the source code.
        """
        # Wizards can read anything
        if player.is_wizard:
            return True

        # Programmers can read readable code
        if player.is_programmer:
            if hasattr(verb_def, 'perms'):
                perms = parse_perms(verb_def.perms)
                if perms & Permission.READ:
                    return True

        # Owner can always read their own code
        if hasattr(verb_def, 'owner') and player.objnum == verb_def.owner:
            return True

        return False

    def can_write_verb_code(self, player: MOOObject, verb_obj: MOOObject,
                           verb_def) -> bool:
        """
        Determine whether *player* may write (modify) the source code of a verb.

        This controls commands like ``@program`` and the verb-editor's "save"
        action.

        Permission rules (evaluated in order, first match wins):
            1. Wizards can write any verb source.
            2. Non-programmers are always denied (they cannot author code).
            3. The verb's *owner* can write **only if** the verb's ``w``
               (WRITE) permission bit is set.
            4. Otherwise, access is denied.

        Args:
            player (MOOObject):  The player attempting to write code.
            verb_obj (MOOObject): The object the verb is defined on.
            verb_def:            The :class:`~moo.verbs.VerbDef` instance.

        Returns:
            bool: ``True`` if the player is allowed to modify the source code.
        """
        # Wizards can write anything
        if player.is_wizard:
            return True

        # Must be a programmer to write any verb code
        if not player.is_programmer:
            return False

        # Owner can write if verb is writable
        if hasattr(verb_def, 'owner') and player.objnum == verb_def.owner:
            if hasattr(verb_def, 'perms'):
                perms = parse_perms(verb_def.perms)
                if perms & Permission.WRITE:
                    return True

        return False

    # -------------------------------------------------------------------------
    # Object lifecycle
    # -------------------------------------------------------------------------

    def can_create_object(self, player: MOOObject, parent_obj: Optional[MOOObject] = None) -> bool:
        """
        Determine whether *player* may create a new object.

        Permission rules:
            1. Wizards can always create objects.
            2. Only programmers (or wizards) may create objects -- regular
               players cannot.
            3. If a *parent_obj* is specified, it must have the ``FERTILE``
               flag set (unless the player is a wizard).  This prevents
               arbitrary cloning of objects the owner did not intend to be
               used as templates.

        Args:
            player (MOOObject):             The player attempting to create.
            parent_obj (MOOObject, optional): The intended parent for the new
                object.  ``None`` if creating without a parent.

        Returns:
            bool: ``True`` if the player is allowed to create the object.
        """
        # Wizards can always create
        if player.is_wizard:
            return True

        # Only programmers can create objects
        if not player.is_programmer:
            return False

        # Check parent is fertile (allows being used as a template)
        if parent_obj:
            if not parent_obj.is_fertile and not player.is_wizard:
                return False

        return True

    def can_recycle_object(self, player: MOOObject, obj: MOOObject) -> bool:
        """
        Determine whether *player* may recycle (permanently delete) *obj*.

        Recycling removes an object from the database entirely.  Because this
        is destructive and can break references, the rules are strict:

            1. Wizards can recycle any object.
            2. The object's *owner* can recycle it, **but only if**:
               a. The object has no children (other objects that inherit
                  from it).  Recycling a parent would orphan its children.
               b. The object has no contents (objects located inside it).
                  This prevents accidental data loss.
            3. Otherwise, access is denied.

        Args:
            player (MOOObject): The player attempting to recycle.
            obj (MOOObject):    The object to be recycled.

        Returns:
            bool: ``True`` if the player is allowed to recycle the object.
        """
        # Wizards can recycle anything
        if player.is_wizard:
            return True

        # Must be owner
        if player.objnum != obj.owner:
            return False

        # Cannot recycle if has children (would orphan them)
        if obj.children:
            return False

        # Cannot recycle if has contents (would lose contained objects)
        if obj._content_ids:
            return False

        return True

    def can_move_object(self, player: MOOObject, obj: MOOObject,
                       destination: MOOObject) -> bool:
        """
        Determine whether *player* may move *obj* to *destination*.

        This controls ``@move`` and the in-game verb-level ``move()`` builtin.

        Permission rules:
            1. Wizards can move any object anywhere.
            2. The object's *owner* can move it.
            3. A player can move objects currently located in their own
               inventory (i.e. ``obj._location_id == player.objnum``),
               regardless of who owns the object.  This allows dropping or
               giving away items.
            4. Otherwise, access is denied.

        Note:
            Destination acceptability (e.g. checking a room's ``accept``
            verb) is handled separately by the move logic in ``builtins.py``.

        Args:
            player (MOOObject):      The player attempting the move.
            obj (MOOObject):         The object to move.
            destination (MOOObject): The target location.

        Returns:
            bool: ``True`` if the player is allowed to perform the move.
        """
        # Wizards can move anything
        if player.is_wizard:
            return True

        # Can move your own objects
        if player.objnum == obj.owner:
            return True

        # Can move objects in your inventory (e.g. to drop them)
        if obj._location_id == player.objnum:
            return True

        return False

    def can_change_parent(self, player: MOOObject, obj: MOOObject,
                         new_parent: MOOObject) -> bool:
        """
        Determine whether *player* may change the parent of *obj*.

        Changing an object's parent re-wires its inheritance chain, which can
        dramatically alter its behaviour.  Rules:

            1. Wizards can change any object's parent.
            2. The object's *owner* can change the parent, **but only if**
               the new parent has the ``FERTILE`` flag set.  This ensures
               the new parent's owner has opted in to being inherited from.
            3. Otherwise, access is denied.

        Args:
            player (MOOObject):     The player attempting the change.
            obj (MOOObject):        The object whose parent will change.
            new_parent (MOOObject): The proposed new parent object.

        Returns:
            bool: ``True`` if the player is allowed to change the parent.
        """
        # Wizards can change anything
        if player.is_wizard:
            return True

        # Must own the object
        if player.objnum != obj.owner:
            return False

        # New parent must be fertile (its owner has opted in to delegation)
        if not new_parent.is_fertile:
            return False

        return True

    def can_set_object_flag(self, player: MOOObject, obj: MOOObject,
                           flag: ObjectFlags) -> bool:
        """
        Determine whether *player* may set (or clear) a flag on *obj*.

        Some flags are security-critical and restricted to wizards:

            1. Wizards can set any flag on any object.
            2. ``WIZARD`` and ``PLAYER`` flags are **wizard-only** -- no one
               else can grant wizard or player status.
            3. The ``PROGRAMMER`` flag can only be set by someone who is
               already a programmer (or wizard).
            4. For all other flags (e.g. ``FERTILE``, ``READABLE``), the
               object's *owner* may set them.
            5. Non-owners are denied.

        Args:
            player (MOOObject):  The player attempting to set the flag.
            obj (MOOObject):     The object to modify.
            flag (ObjectFlags):  The flag to set or clear.

        Returns:
            bool: ``True`` if the player is allowed to change the flag.
        """
        # Wizards can set anything
        if player.is_wizard:
            return True

        # Wizard and player flags are wizard-only
        if flag in (ObjectFlags.WIZARD, ObjectFlags.PLAYER):
            return False

        # Must own the object
        if player.objnum != obj.owner:
            return False

        # Programmer flag requires being a programmer already
        if flag == ObjectFlags.PROGRAMMER and not player.is_programmer:
            return False

        return True

    # -------------------------------------------------------------------------
    # Effective permissions (setuid behaviour)
    # -------------------------------------------------------------------------

    def get_effective_perms(self, player: MOOObject, task_obj: Optional[MOOObject] = None) -> MOOObject:
        """
        Determine the effective permission context for a running task.

        In MOO, a verb can run with the permissions of the object it is
        defined on rather than the calling player.  This is analogous to
        Unix's setuid mechanism and is used so that, e.g., a locked door
        verb can check and modify its own properties even when called by
        an unprivileged player.

        The rule implemented here is conservative: the task object's
        permissions are only used if they are *higher* (specifically, if
        the task object is a wizard).  Otherwise the player's own
        permissions apply.

        Args:
            player (MOOObject):            The player who initiated the task.
            task_obj (MOOObject, optional): The object whose permissions should
                be considered (typically the object the verb is defined on).

        Returns:
            MOOObject: The object whose permission level should be used for
            access checks during the task.
        """
        # If task_obj specified and has higher permissions, use those
        if task_obj and task_obj.is_wizard:
            return task_obj

        # Otherwise use player's permissions
        return player

    # -------------------------------------------------------------------------
    # Quota management
    # -------------------------------------------------------------------------

    def check_quota(self, player: MOOObject, cost: int = 1) -> bool:
        """
        Check whether *player* has sufficient quota to perform an operation.

        MOO uses a quota system to prevent any single player from consuming
        excessive server resources (e.g. creating thousands of objects).
        Each player has a ``quota`` property that is decremented when they
        create objects or perform other quota-costed actions.

        Args:
            player (MOOObject): The player to check.
            cost (int):         The quota cost of the intended operation.
                                Defaults to ``1``.

        Returns:
            bool: ``True`` if the player has enough quota (or is exempt).

        Note:
            Wizards have unlimited quota and always return ``True``.
            If the player has no ``quota`` property at all, the check
            is permissive (returns ``True``) to avoid breaking setups
            that do not use quotas.
        """
        # Wizards have unlimited quota
        if player.is_wizard:
            return True

        # Get player's quota
        try:
            quota = player.get_property('quota', self.database)
            if quota is None:
                # No quota set -- allow the operation (permissive default)
                return True

            # Check if sufficient quota remains
            return quota >= cost
        except Exception:
            # Error getting quota -- allow rather than block
            return True

    def deduct_quota(self, player: MOOObject, cost: int = 1):
        """
        Deduct *cost* from *player*'s quota after a successful operation.

        Should be called **after** :meth:`check_quota` returns ``True`` and
        the operation has been performed.  Wizards are silently skipped
        (they do not consume quota).

        Args:
            player (MOOObject): The player to deduct from.
            cost (int):         The amount to deduct.  Defaults to ``1``.

        Raises:
            No exceptions are raised.  Errors during quota update are logged
            and silently swallowed to avoid disrupting the operation that
            already succeeded.
        """
        # Wizards don't use quota
        if player.is_wizard:
            return

        try:
            quota = player.get_property('quota', self.database)
            if quota is not None:
                new_quota = quota - cost
                player.set_property('quota', new_quota, self.database)
                logger.debug(f"Deducted {cost} quota from #{player.objnum}, remaining: {new_quota}")
        except Exception:
            pass
