"""
MegaMOO Utility Functions
==========================

A collection of general-purpose helper functions and classes used throughout
the MegaMOO server.  These utilities are not tied to any single subsystem;
instead they provide cross-cutting functionality (string manipulation, time
formatting, hashing, validation, logging, and interactive session management)
that multiple modules depend on.

Module Organisation
-------------------
The utilities are grouped into logical sections:

* **String Utilities** -- object-reference parsing, English article selection,
  capitalisation, wildcard pattern matching.
* **Time Utilities** -- human-readable elapsed-time formatting.
* **Hashing and Security** -- MOO-compatible password hashing (SHA-256 based)
  and random string generation.
* **Data Structure Utilities** -- recursive list flattening, safe index lookup.
* **Validation Utilities** -- name and object-number validation for user input.
* **Logging Utilities** -- convenience wrappers around Python's ``logging``
  module for consistent command and error logging.
* **Interactive Session System** -- the :class:`InteractiveSession` class and
  :func:`interactive` decorator that enable generator-based multi-step
  player interactions (prompts, timed pauses, input collection), inspired
  by Evennia's ``@interactive`` pattern.

Architecture Notes
------------------
* Functions in this module are pure (no side effects on the database) with
  the exception of the logging helpers and the interactive session system.
* The :func:`interactive` decorator integrates with the network layer
  (``network.get_connection_for_player``) and the verb context system
  (``verb_context.set_verb_context``), but the decorator itself lives here
  because it is used across many different verb and command modules.
* Password hashing uses SHA-256 rather than the classic Unix ``crypt(3)``
  for improved security while maintaining API compatibility.

See Also
--------
* ``builtins.py`` -- MOO builtins that wrap some of these utilities for
  verb-code use.
* ``network.py``  -- Connection management that the interactive system
  hooks into.

Copyright (c) 2026
License: MIT
"""

from contextlib import contextmanager
from typing import Any, List, Optional, Union
import re
import hashlib
import random
import string
import logging

logger = logging.getLogger('megamoo.utils')


# =============================================================================
# STRING UTILITIES
# =============================================================================

def parse_object_ref(text: str) -> Optional[int]:
    """
    Extract an object reference (dbref) from a string.

    Scans *text* for the first occurrence of the ``#<digits>`` pattern
    (the MOO convention for referencing objects by number) and returns
    the integer object number.  If no match is found, returns ``None``.

    This is useful for parsing player input that may embed an object
    reference anywhere in the string, e.g. ``"look at #123"`` or
    ``"Object #456 is broken"``.

    Args:
        text (str): Arbitrary string that may contain a ``#N`` reference.

    Returns:
        int or None: The extracted object number, or ``None`` if no
        reference was found.

    Examples::

        >>> parse_object_ref("#123")
        123
        >>> parse_object_ref("Object #456 is broken")
        456
        >>> parse_object_ref("nothing here")
        None
    """
    match = re.search(r'#(\d+)', text)
    if match:
        return int(match.group(1))
    return None


def article(word: str) -> str:
    """
    Return the appropriate English indefinite article for *word*.

    Handles common special cases (silent *h* in "honest", "hour", "heir")
    and the standard vowel-initial rule.  This is a best-effort heuristic
    -- English has many irregular cases that are not covered here.

    Args:
        word (str): The word to determine the article for.

    Returns:
        str: ``'an'`` if *word* begins with a vowel sound, ``'a'`` otherwise.

    Examples::

        >>> article('apple')
        'an'
        >>> article('banana')
        'a'
        >>> article('honest')
        'an'
        >>> article('')
        'a'
    """
    if not word:
        return 'a'

    # Check for special cases: words with a silent 'h' where the vowel
    # sound comes through (e.g. "honest", "hour", "heir").
    word_lower = word.lower()
    if word_lower.startswith(('honest', 'hour', 'heir')):
        return 'an'

    # Standard rule: vowel-initial words get 'an'
    if word_lower[0] in 'aeiou':
        return 'an'

    return 'a'


def match_pattern(text: str, pattern: str, case_sensitive: bool = False) -> bool:
    """
    Match text against a wildcard pattern.

    Converts MOO-style wildcard patterns to regular expressions and tests
    for a full match (the pattern must cover the entire string, not just a
    substring).

    Pattern syntax:
        ``*``  -- Matches any sequence of zero or more characters.
        ``?``  -- Matches exactly one character.
        All other characters are treated as literals.

    Args:
        text (str):           The text to test.
        pattern (str):        The wildcard pattern.
        case_sensitive (bool): Whether the match should be case-sensitive.
            Defaults to ``False`` (case-insensitive).

    Returns:
        bool: ``True`` if *text* matches *pattern*.

    Examples::

        >>> match_pattern('hello', 'h*')
        True
        >>> match_pattern('hello', 'h?llo')
        True
        >>> match_pattern('hello', 'world')
        False
        >>> match_pattern('Hello', 'hello', case_sensitive=True)
        False
    """
    # Convert MOO wildcard pattern to a Python regex:
    # 1. Escape all regex metacharacters in the pattern.
    # 2. Replace the escaped wildcard placeholders with their regex equivalents.
    # 3. Anchor the pattern to match the full string.
    regex_pattern = re.escape(pattern).replace(r'\*', '.*').replace(r'\?', '.')
    regex_pattern = f'^{regex_pattern}$'

    flags = 0 if case_sensitive else re.IGNORECASE
    return bool(re.match(regex_pattern, text, flags))


# =============================================================================
# TIME UTILITIES
# =============================================================================

def elapsed_time(seconds: float) -> str:
    """
    Format a duration in seconds as a human-readable English string.

    Produces output like ``"1 hour, 5 minutes, 30 seconds"`` with correct
    singular/plural forms.  Suitable for displaying connection durations,
    object ages, and other time intervals to players.

    The function progressively decomposes *seconds* into hours, minutes,
    and remaining seconds.  Zero-value components are omitted (except when
    the total is less than 60 seconds, in which case seconds are always
    shown).

    Args:
        seconds (float): The number of seconds to format.  Fractional
            seconds are truncated to integers.

    Returns:
        str: Human-readable elapsed time string.

    Examples::

        >>> elapsed_time(30)
        '30 seconds'
        >>> elapsed_time(90)
        '1 minute, 30 seconds'
        >>> elapsed_time(3665)
        '1 hour, 1 minute, 5 seconds'
        >>> elapsed_time(3600)
        '1 hour'
    """
    if seconds < 60:
        return f"{int(seconds)} second{'s' if seconds != 1 else ''}"

    minutes = int(seconds // 60)
    seconds = int(seconds % 60)

    if minutes < 60:
        parts = [f"{minutes} minute{'s' if minutes != 1 else ''}"]
        if seconds > 0:
            parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
        return ', '.join(parts)

    hours = int(minutes // 60)
    minutes = int(minutes % 60)

    parts = [f"{hours} hour{'s' if hours != 1 else ''}"]
    if minutes > 0:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if seconds > 0:
        parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
    return ', '.join(parts)


# =============================================================================
# HASHING AND SECURITY
# =============================================================================

def generate_random_string(length: int = 32) -> str:
    """
    Generate a random alphanumeric string.

    Useful for creating session tokens, temporary passwords, and other
    non-cryptographic random identifiers.

    Args:
        length (int): The desired string length.  Defaults to ``32``.

    Returns:
        str: A random string of the specified length, composed of
        ASCII letters (upper and lower) and digits.
    """
    return ''.join(random.choices(
        string.ascii_letters + string.digits,
        k=length
    ))


# =============================================================================
# DATA STRUCTURE UTILITIES
# =============================================================================

def flatten_list(nested_list: List) -> List:
    """
    Recursively flatten a nested list structure into a single flat list.

    Non-list elements are preserved as-is at their encountered position.
    Only ``list`` instances are recursed into -- other iterables (tuples,
    sets, etc.) are treated as leaf values.

    Args:
        nested_list (List): A potentially nested list.

    Returns:
        List: A single-level list with all elements in depth-first order.

    Examples::

        >>> flatten_list([1, [2, 3], [4, [5, 6]]])
        [1, 2, 3, 4, 5, 6]
        >>> flatten_list([])
        []
        >>> flatten_list([1, 2, 3])
        [1, 2, 3]
    """
    result = []
    for item in nested_list:
        if isinstance(item, list):
            result.extend(flatten_list(item))
        else:
            result.append(item)
    return result


def safe_index(lst: List, item: Any, start: int = 0) -> int:
    """
    Find the index of *item* in *lst*, returning ``-1`` if not found.

    A safe alternative to ``list.index()`` that never raises
    :class:`ValueError`.  Follows the convention used by ``str.find()``
    of returning ``-1`` for "not found".

    Args:
        lst (List): The list to search.
        item (Any): The item to find.
        start (int): The index to start searching from.  Defaults to ``0``.

    Returns:
        int: The index of *item*, or ``-1`` if *item* is not in *lst*.
    """
    try:
        return lst.index(item, start)
    except ValueError:
        return -1


# =============================================================================
# VALIDATION UTILITIES
# =============================================================================

def is_valid_name(name: str) -> bool:
    """
    Check whether a string is a valid MOO identifier.

    Valid names follow Python/C identifier rules: they must start with a
    letter or underscore and contain only letters, digits, and underscores.
    This is used to validate object names, property names, and verb names
    before they are committed to the database.

    Args:
        name (str): The name to validate.

    Returns:
        bool: ``True`` if the name is a valid identifier, ``False`` otherwise.

    Rules:
        - Must not be empty.
        - Must start with a letter (``a-z``, ``A-Z``) or underscore (``_``).
        - May contain letters, digits (``0-9``), and underscores.
        - Spaces and special characters are not allowed.

    Examples::

        >>> is_valid_name('my_sword')
        True
        >>> is_valid_name('_private')
        True
        >>> is_valid_name('3rd_item')
        False
        >>> is_valid_name('')
        False
    """
    if not name:
        return False
    return bool(re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name))


def is_valid_objnum(objnum: int) -> bool:
    """
    Check whether an integer is a valid object number.

    Object numbers in MOO are non-negative integers.  Negative values
    are used as sentinels (e.g. ``-1`` means "no object" or "nothing").

    Args:
        objnum (int): The value to validate.

    Returns:
        bool: ``True`` if *objnum* is a non-negative integer.

    Examples::

        >>> is_valid_objnum(0)
        True
        >>> is_valid_objnum(42)
        True
        >>> is_valid_objnum(-1)
        False
    """
    return isinstance(objnum, int) and objnum >= 0


# =============================================================================
# LOGGING UTILITIES
# =============================================================================

def log_command(player_objnum: int, command: str):
    """
    Log a player command execution at the INFO level.

    Creates a consistent log format (``#<objnum>: <command>``) that is
    easy to grep for when investigating player activity or debugging
    command parsing issues.

    Args:
        player_objnum (int): The object number of the player who issued
            the command.
        command (str): The raw command string.
    """
    logger.info(f"#{player_objnum}: {command}")


def log_error(error: Exception, context: str = ''):
    """
    Log an error with optional context and full traceback.

    Logs at the ERROR level with ``exc_info=True`` to include the
    traceback.  If *context* is provided, it is prepended to the error
    message for easier identification in log files.

    Args:
        error (Exception): The exception to log.
        context (str):     Optional context string (e.g. the function name
            or operation that failed).
    """
    if context:
        logger.error(f"{context}: {error}", exc_info=True)
    else:
        logger.error(str(error), exc_info=True)


# =============================================================================
# INTERACTIVE SESSION SYSTEM
# =============================================================================

class InteractiveSession:
    """
    Manages a suspended generator that is waiting for player input.

    When a verb decorated with :func:`interactive` is called, it produces
    a Python generator.  The generator ``yield`` s to pause execution,
    and this class manages the bookkeeping between yields:

    - Storing the generator and tracking its state (waiting, finished, error).
    - Advancing the generator to its first ``yield`` via :meth:`start`.
    - Feeding player input into the generator via :meth:`resume`.
    - Cancelling the session via :meth:`cancel` (sends ``GeneratorExit``).
    - Reporting errors back to the player.

    Yield Semantics
    ----------------
    The value yielded by the generator determines what happens next:

    - **``str`` or ``None``** -- Wait for the player's next line of input.
      If a string is yielded, it can be used as a prompt.  The player's
      response becomes the return value of the ``yield`` expression.
    - **``int`` or ``float``** -- Pause for that many seconds, then
      auto-resume with ``None`` as the yield return value.  The server
      remains responsive during the pause (it is not a blocking sleep).

    Attributes:
        generator:   The suspended generator object.
        player_obj:  The :class:`~moo.objects.MOOObject` for the player
                     driving this session.
        db:          The :class:`~moo.database.Database` instance (used
                     for verb context setup).
        prompt:      The last value yielded by the generator.  Determines
                     the wait mode (see Yield Semantics above).
        finished:    ``True`` once the generator has returned or raised.
        error:       The exception, if the generator raised one.

    See Also:
        :func:`interactive` -- the decorator that creates and installs
        these sessions.
    """

    def __init__(self, generator, player_obj, db=None, verb_owner=None):
        """
        Create a new interactive session.

        Args:
            generator:   A generator object (the return value of calling
                         an ``@interactive``-decorated function).
            player_obj:  The player's :class:`~moo.objects.MOOObject`.
            db:          The database instance.  If ``None``, attempts to
                         read ``player_obj._database`` as a fallback.
        """
        self.generator = generator
        self.player_obj = player_obj
        self.db = db or getattr(player_obj, '_database', None)
        self.prompt = None
        self.finished = False
        self.error = None
        # Who the paused verb runs as.
        #
        # The body between two yields is still that verb, but it resumes
        # long after the call frame is gone -- so without this, a write
        # from the second half was attributed to the *player* rather than
        # to the verb's owner, and chargen could not write to the account
        # it had just been asked to fill in.  Passed in by the caller,
        # which still has the VerbDef; there is nothing left to read it
        # from by the time we get here.
        self.verb_owner = verb_owner

    # -------------------------------------------------------------------------
    # State inspection properties
    # -------------------------------------------------------------------------

    @property
    def is_timed_pause(self) -> bool:
        """
        ``True`` if the current yield is a timed pause (the generator
        yielded a numeric value rather than a string or ``None``).
        """
        return isinstance(self.prompt, (int, float))

    @property
    def pause_seconds(self) -> float:
        """
        The number of seconds to sleep for a timed pause.

        Returns ``0.0`` if the current yield is not a timed pause.
        Negative values yielded by the generator are clamped to ``0``.
        """
        if self.is_timed_pause:
            return max(0, float(self.prompt))
        return 0.0

    # -------------------------------------------------------------------------
    # Lifecycle methods
    # -------------------------------------------------------------------------

    @contextmanager
    def _as_verb(self):
        """
        Advance the generator with the paused verb's permissions.

        A generator step is a continuation of the verb that created it,
        but it runs long after that verb's call frame was popped -- so
        anything it writes would otherwise be attributed to the player
        who typed the line rather than to the verb's owner.  For chargen
        that meant being refused the account it exists to fill in.
        """
        from .builtins import push_frame, pop_frame, current_perms
        framed = False
        try:
            push_frame(self.player_obj, '<interactive>', None,
                       self.player_obj, owner=self.verb_owner)
            framed = True
        except Exception:                       # never block the session
            pass
        try:
            yield
        finally:
            if framed:
                # Carry the effective owner into the next segment before the
                # frame goes.  A verb that opened with
                # `set_task_perms(caller_perms())` and then yielded a prompt
                # used to have that drop thrown away on resume: the session
                # was built with the *static* VerbDef owner, so every write
                # after the yield went back to acting as staff.  @rmprop
                # prompts "are you sure?", which put all of its work on the
                # far side of exactly that.
                #
                # MOO's set_task_perms lasts the task, so persisting it
                # across a pause is the semantic anyway.
                try:
                    self.verb_owner = current_perms()
                except Exception:
                    pass
                try:
                    pop_frame()
                except Exception:
                    pass

    def start(self):
        """
        Advance the generator to its first ``yield``.

        Must be called once after construction to "prime" the generator.
        If the generator returns immediately (never yields), ``finished``
        is set to ``True``.

        Returns:
            InteractiveSession: ``self``, for method chaining.
        """
        from .verb_context import set_verb_context, clear_verb_context
        token = set_verb_context(self.player_obj, self.db, 0) if self.db else None
        try:
            with self._as_verb():
                self.prompt = next(self.generator)
        except StopIteration:
            # Generator returned immediately -- nothing to wait for
            self.finished = True
        except Exception as exc:
            self.finished = True
            self.error = exc
            self._report_error(exc)
        finally:
            if token is not None:
                clear_verb_context(token)
        return self

    def resume(self, player_input=None):
        """
        Send *player_input* into the generator and advance to the next
        ``yield`` (or the end).

        Called by the command loop when the player types a line during an
        active interactive session, or by the scheduler when a timed pause
        expires.

        Args:
            player_input: The line the player typed (``str``), or ``None``
                when resuming from a timed pause.
        """
        from .verb_context import set_verb_context, clear_verb_context
        token = set_verb_context(self.player_obj, self.db, 0) if self.db else None
        try:
            with self._as_verb():
                self.prompt = self.generator.send(player_input)
        except StopIteration:
            # Generator finished normally
            self.finished = True
            self.prompt = None
        except Exception as exc:
            self.finished = True
            self.error = exc
            self._report_error(exc)
        finally:
            if token is not None:
                clear_verb_context(token)

        # A multi-step verb does its work *here*, not in the command that
        # started it: ``@delete`` recycles what you are holding only once
        # you have answered its "are you sure?".  Both command loops feed
        # that answer straight into the generator and ``continue``, so
        # nothing on this path goes through ``execute_command``, and
        # without this the announce there never fires for the step that
        # actually changed anything.
        #
        # In ``resume()`` rather than in each command loop because there
        # are two of those -- telnet and web -- and they would drift.
        #
        # Free for a client that cannot show an inventory: the announce
        # returns immediately unless the connection negotiated GMCP,
        # which a plain telnet session never does.
        try:
            from .builtins import send_inventory_gmcp
            send_inventory_gmcp(self.player_obj)
        except Exception:
            pass
        try:
            from .builtins import send_vitals_gmcp
            send_vitals_gmcp(self.player_obj)
        except Exception:
            pass

    def cancel(self):
        """
        Abort the interactive session.

        Sends ``GeneratorExit`` into the generator, which triggers any
        ``finally`` blocks in the generator function.  After cancellation,
        ``finished`` is ``True`` and no further ``resume()`` calls should
        be made.
        """
        self.finished = True
        self.prompt = None
        try:
            self.generator.close()
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Error reporting
    # -------------------------------------------------------------------------

    def _report_error(self, exc):
        """
        Send an error message to the player and log the traceback.

        Args:
            exc (Exception): The exception that occurred.
        """
        if hasattr(self.player_obj, 'objnum'):
            from .builtins import notify
            notify(self.player_obj, f"Error in interactive session: {exc}")
        logger.error(f"Interactive session error for #{self.player_obj.objnum}: {exc}",
                     exc_info=True)

    def __repr__(self):
        state = 'finished' if self.finished else 'waiting'
        return f"InteractiveSession({state}, player=#{self.player_obj.objnum})"


# =============================================================================
# @interactive DECORATOR
# =============================================================================

def interactive(func):
    """
    Decorator that turns a generator function into an interactive prompt session.

    This is MegaMOO's equivalent of Evennia's ``@interactive`` decorator.
    The decorated function becomes a generator that can ``yield`` to pause
    execution and wait for either player input or a timed delay.

    Yield Semantics
    ----------------
    Inside the decorated function:

    - **``yield "prompt text"``** or **``yield None``** -- Pause and wait
      for the player's next line of input.  If a string is yielded, it is
      sent to the player as a prompt.  The player's response becomes the
      return value of the ``yield`` expression.

    - **``yield <number>``** -- Pause for that many seconds (int or float),
      then auto-resume.  The ``yield`` expression returns ``None``.  The
      server remains fully responsive during the pause.

    The player can type ``@abort`` during an input wait to cancel the
    session and return to normal command processing.

    How It Works
    ------------
    1. When the decorated function is called, the decorator extracts the
       player object (from the first positional argument or the ``player``
       keyword argument).
    2. It looks up the player's network connection via
       ``network.get_connection_for_player()``.
    3. It calls the original function to get a generator, wraps it in an
       :class:`InteractiveSession`, and calls :meth:`~InteractiveSession.start`
       to advance to the first ``yield``.
    4. The session is stored on the connection as ``_interactive_session``.
    5. The command loop detects the session and routes subsequent player
       input to :meth:`~InteractiveSession.resume` instead of the normal
       command parser.

    Usage in Verb Code::

        @interactive
        def dramatic_entrance(player, this, db, **kwargs):
            player.msg("The ground begins to shake...")
            yield 3                            # pause 3 seconds
            player.msg("A portal opens!")
            yield 1.5                          # pause 1.5 seconds
            name = yield "Who dares enter? "   # wait for input
            player.msg(f"{name} steps through.")

        # Call from verb code:
        dramatic_entrance(player, this, db)

    Args:
        func (callable): A generator function (must contain at least one
            ``yield`` expression).

    Returns:
        callable: A wrapper function that, when called, creates and starts
        an :class:`InteractiveSession`.

    Raises:
        ValueError: If the player object cannot be found in the arguments.
        RuntimeError: If the player has no active network connection.
    """
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        # ----- Locate the player object ------------------------------------
        player_obj = kwargs.get('player')
        if player_obj is None and args:
            player_obj = args[0]

        if player_obj is None:
            raise ValueError(
                f"@interactive: cannot find player object in call to {func.__name__}(). "
                "Pass it as the first positional argument or as player=..."
            )

        # ----- Get the network connection ----------------------------------
        from .network import get_connection_for_player
        conn = get_connection_for_player(player_obj.objnum)
        if conn is None:
            raise RuntimeError(
                f"@interactive: player #{player_obj.objnum} has no active connection"
            )

        # ----- Create the generator and start the session ------------------
        gen = func(*args, **kwargs)
        session = InteractiveSession(gen, player_obj).start()

        if session.finished:
            # Generator didn't yield at all -- nothing to store.
            return

        # Cancel any existing interactive session on this connection
        # (a player can only have one active session at a time)
        prev = getattr(conn, '_interactive_session', None)
        if prev and not prev.finished:
            prev.cancel()

        conn._interactive_session = session

    return wrapper
