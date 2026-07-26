"""
MegaMOO Property Management Utilities

This module provides utility functions and classes for working with MOO
object properties.  Properties are named values attached to MOO objects
(rooms, items, players, etc.) and are the primary mechanism for storing
persistent object state.

Key concepts
------------

* **Properties can be ANY Python type** -- int, str, list, dict, set,
  tuple, custom objects, etc.  This is far more powerful than classic
  LambdaMOO, which was limited to: int, float, str, list, obj, err.

* **MOOObjectRef** wraps an integer object number (``#123``) so that
  object references can be distinguished from plain integers when stored
  as property values.

* **MOOError** represents MOO error codes as first-class values (just
  like in LambdaMOO).  Errors such as ``E_PERM``, ``E_PROPNF``, and
  ``E_TYPE`` can be stored in variables, compared, and raised.

* **PropertyInfo** contains helpers for parsing and formatting property
  specification strings used by builder commands (e.g. ``"strength rc"``).

Architecture
------------

This module is imported throughout the codebase wherever property values
are read, written, or introspected.  The classes defined here are
lightweight value types with no dependency on the database layer, so they
can be safely imported at module level without circular-import issues.

Copyright (c) 2026
License: MIT
"""

from typing import Any, Dict, List, Optional, Tuple, Union
import re
import logging

logger = logging.getLogger('megamoo.properties')


# =============================================================================
# MOOObjectRef -- Object Reference Value Type
# =============================================================================

class MOOObjectRef:
    """
    Reference to a MOO object by its object number.

    In MOO, object references are written as ``#123``.  This class wraps
    a non-negative integer object number so it can be distinguished from
    a regular Python ``int`` when stored in properties, passed to
    builtins, or serialised to the database.

    Instances are **hashable** and support equality comparison, so they
    can be used as dict keys and set members.

    Attributes:
        objnum (int): The non-negative integer object number.

    Examples::

        ref = MOOObjectRef(42)
        str(ref)          # '#42'
        ref == MOOObjectRef(42)  # True
        ref == 42                # False  (int is not MOOObjectRef)
    """

    def __init__(self, objnum: int):
        """
        Create an object reference.

        Args:
            objnum: Non-negative integer object number.

        Raises:
            ValueError: If *objnum* is not a non-negative integer.
        """
        if not isinstance(objnum, int) or objnum < 0:
            raise ValueError(f"Invalid object number: {objnum}")
        self.objnum = objnum

    def __repr__(self) -> str:
        return f"MOOObjectRef(#{self.objnum})"

    def __str__(self) -> str:
        return f"#{self.objnum}"

    def __eq__(self, other) -> bool:
        if isinstance(other, MOOObjectRef):
            return self.objnum == other.objnum
        return False

    def __hash__(self) -> int:
        return hash(self.objnum)

    @classmethod
    def parse(cls, text: str) -> Optional['MOOObjectRef']:
        """
        Parse an object reference from a string like ``"#123"``.

        Accepts leading/trailing whitespace.  The ``#`` prefix is
        required; bare numbers are not accepted.

        Args:
            text: String to parse (e.g. ``"#123"``, ``" #0 "``).

        Returns:
            A new ``MOOObjectRef`` if *text* matches the ``#<digits>``
            pattern, or ``None`` if the format is invalid.

        Examples::

            MOOObjectRef.parse('#42')   # MOOObjectRef(#42)
            MOOObjectRef.parse('hello') # None
            MOOObjectRef.parse('#-1')   # None
        """
        match = re.match(r'#(\d+)', text.strip())
        if match:
            return cls(int(match.group(1)))
        return None


# =============================================================================
# MOOError -- First-class Error Value Type
# =============================================================================

class MOOError(Exception):
    """
    MOO error value -- a first-class error that can be stored and compared.

    In MOO, errors are not just exceptions; they are values that can be
    assigned to variables, stored in properties, returned from functions,
    and compared with ``==``.  Common codes include:

    ============  ================================================
    Code          Meaning
    ============  ================================================
    ``E_NONE``    No error (success sentinel).
    ``E_TYPE``    Type mismatch.
    ``E_DIV``     Division by zero.
    ``E_PERM``    Permission denied.
    ``E_PROPNF``  Property not found.
    ``E_VERBNF``  Verb not found.
    ``E_VARNF``   Variable not found.
    ``E_INVIND``  Invalid indirection (bad object reference).
    ``E_RECMOVE`` Recursive move.
    ``E_MAXREC``  Maximum recursion depth exceeded.
    ``E_RANGE``   Index out of range.
    ``E_ARGS``    Wrong number of arguments.
    ``E_NACC``    Move refused by destination.
    ``E_INVARG``  Invalid argument value.
    ``E_QUOTA``   Resource quota exceeded.
    ``E_FLOAT``   Floating-point error.
    ============  ================================================

    MOOError is also a subclass of ``Exception``, so it can be raised
    and caught in verb code with standard Python ``try``/``except``.

    Attributes:
        code (str):    Error code string (e.g. ``'E_PERM'``).
        message (str): Optional human-readable error message.
    """

    # --- Standard MOO error code constants ---
    E_NONE = 'E_NONE'
    E_TYPE = 'E_TYPE'
    E_DIV = 'E_DIV'
    E_PERM = 'E_PERM'
    E_PROPNF = 'E_PROPNF'
    E_VERBNF = 'E_VERBNF'
    E_VARNF = 'E_VARNF'
    E_INVIND = 'E_INVIND'
    E_RECMOVE = 'E_RECMOVE'
    E_MAXREC = 'E_MAXREC'
    E_RANGE = 'E_RANGE'
    E_ARGS = 'E_ARGS'
    E_NACC = 'E_NACC'
    E_INVARG = 'E_INVARG'
    E_QUOTA = 'E_QUOTA'
    E_FLOAT = 'E_FLOAT'

    def __init__(self, code: str, message: str = ''):
        """
        Create a MOO error value.

        Args:
            code:    Error code string (e.g. ``'E_PERM'``).
            message: Optional human-readable description.  If omitted,
                     the code itself is used as the exception message.
        """
        super().__init__(message or code)
        self.code = code
        self.message = message

    def __repr__(self) -> str:
        if self.message:
            return f"MOOError({self.code}, '{self.message}')"
        return f"MOOError({self.code})"

    def __str__(self) -> str:
        return self.code

    def __eq__(self, other) -> bool:
        if isinstance(other, MOOError):
            return self.code == other.code
        return False

    def __hash__(self) -> int:
        return hash(self.code)


# =============================================================================
# PropertyInfo -- Property Specification Parsing / Formatting
# =============================================================================

class PropertyInfo:
    """
    Utility class for parsing and formatting property specification
    strings used by builder commands like ``@set`` and ``@property``.

    A property specification has the format::

        "name [perms]"

    where *perms* is a permission string consisting of characters:

    * ``r`` -- readable by others
    * ``w`` -- writable by others
    * ``c`` -- inherited by children (chown)

    If no permission string is given, the default ``"rc"`` is used
    (readable and inheritable).

    Properties in MegaMOO can be any Python type: dict, list, set, int,
    str, etc.  This provides much more flexibility than traditional MOO.
    """

    @staticmethod
    def parse_spec(spec: str) -> Dict[str, str]:
        """
        Parse a property specification string into its components.

        Format: ``"name [perms]"``

        Args:
            spec: Specification string to parse.

        Returns:
            A dict with keys:

            * ``'name'`` -- the property name (first whitespace-delimited token)
            * ``'perms'`` -- the permission string (second token, or ``'rc'``
              if omitted)

        Examples::

            PropertyInfo.parse_spec("strength rc")
            # {'name': 'strength', 'perms': 'rc'}

            PropertyInfo.parse_spec("description r")
            # {'name': 'description', 'perms': 'r'}

            PropertyInfo.parse_spec("contents rwc")
            # {'name': 'contents', 'perms': 'rwc'}

            PropertyInfo.parse_spec("hidden")
            # {'name': 'hidden', 'perms': 'rc'}  (default perms)
        """
        parts = spec.split()

        result = {
            'name': parts[0] if parts else '',
            'perms': 'rc'
        }

        if len(parts) > 1:
            result['perms'] = parts[1]

        return result

    @staticmethod
    def format_spec(name: str, perms: str = 'rc') -> str:
        """
        Format a property name and permissions into a specification string.

        This is the inverse of :meth:`parse_spec`.

        Args:
            name:  Property name.
            perms: Permission string (default ``'rc'``).

        Returns:
            Formatted specification string, e.g. ``"strength rc"``.
        """
        return f'{name} {perms}'
