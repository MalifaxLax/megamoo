"""
MegaMOO Command Parser

This module parses player input into executable commands, extracting verbs,
objects, and prepositions according to MOO conventions.

Architecture Overview::

    Raw input string
        │
        ▼
    CommandParser.parse()
        │
        ├── Prefixed?  (@cmd / +cmd)
        │       └── _parse_prefixed_command()
        │
        ├── Slash eval?  (/expression)
        │       └── verb='/', argstr=expression
        │
        └── Normal verb
                │
                ├── _find_verb()          ← search player, location, contents
                │       └── obj.find_verb()   (walks inheritance chain)
                │
                └── _parse_arguments()    ← split argstr into dobj/prep/iobj
                        └── _extract_objects()
                                ├── special-prep scan  (= and ?)
                                ├── word-by-word prep scan
                                └── _match_object()   ← ObjectMatcher

The parser follows classic LambdaMOO semantics with a few MegaMOO
extensions:

- **Switch syntax**: ``verb/switch1/switch2`` is split so that the verb
  name and switch list are available separately (used by builder
  commands like ``@dig/teleport``).
- **Special prepositions**: ``=`` and ``?`` act as single-character
  prepositions so that property-setting shorthand (``obj.prop = value``)
  works naturally.
- **Slash eval**: A bare ``/`` followed by a Python expression is
  routed to the eval verb.

Command Format:
    <verb> [direct-object] [preposition] [indirect-object]

Examples:
    get lamp
    put sword in bag
    give flower to wizard
    @create $thing named "Magic Sword"
    look/quiet north
    /2 + 2

Copyright (c) 2026
License: MIT
"""

# ============================================================
# IMPORTS
# ============================================================

from typing import Optional, Tuple, List, Any
from dataclasses import dataclass
from enum import Enum
import re
import logging

from .match import ObjectMatcher, MatchScope, match_preposition, MatchError
from .objects import MOOObject

logger = logging.getLogger('megamoo.parser')


# ============================================================
# CONSTANTS AND ENUMS
# ============================================================


class ArgSpec(Enum):
    """
    Argument specifications for verb direct/indirect object slots.

    Every verb definition declares what its direct-object and
    indirect-object slots accept.  The parser consults these specs to
    decide whether to attempt object matching or treat the text as a
    plain string.

    Values:
        NONE: The slot must be empty.  If the player supplies text in
            this position it is ignored (or treated as part of ``args``).
        ANY:  The slot accepts either a matched in-game object *or* an
            unresolved string.  The parser tries ``ObjectMatcher`` first;
            if no object is found the raw text is kept as ``dobjstr`` /
            ``iobjstr`` and the numeric field is set to ``0``.
        THIS: The slot must resolve to the object the verb is defined
            on.  Resolution is deferred to verb execution time.
    """
    NONE = 'none'      # No argument allowed
    ANY = 'any'        # Any text or object
    THIS = 'this'      # Must match this object


# ============================================================
# PARSE RESULT
# ============================================================


@dataclass
class ParseResult:
    """
    The fully-resolved output of ``CommandParser.parse()``.

    Every field is populated by the parser before the result is handed
    to the server for verb execution.  Verb code accesses most of these
    values through the namespace variables ``dobj``, ``dobjstr``,
    ``iobj``, ``iobjstr``, ``prepstr``, ``args``, ``argstr``, and
    ``switches``.

    Attributes:
        verb (str): The canonical verb name that was matched.  For
            prefixed commands this includes the prefix (e.g. ``"@dig"``).
        verb_obj (int): Object number of the object on which the verb
            definition was found (after walking the inheritance chain).
        dobj (int): Object number of the direct object, or ``0`` if the
            direct-object text did not resolve to an in-game object.
        dobjstr (str): The raw direct-object text as the player typed it
            (e.g. ``"magic sword"``).
        prep (str): The matched preposition string (e.g. ``"in"``,
            ``"to"``, ``"="``), or ``''`` if no preposition was found.
        iobj (int): Object number of the indirect object, or ``0``.
        iobjstr (str): Raw indirect-object text.
        argstr (str): Everything after the verb, unparsed.  Useful for
            verbs that want to do their own argument splitting.
        args (list): The argument string split into tokens.
        switches (list[str]): Slash-separated switches extracted from
            the verb token (e.g. ``["quiet", "teleport"]`` from
            ``@dig/quiet/teleport``).
    """
    verb: str
    verb_obj: int
    dobj: int = 0
    dobjstr: str = ''
    prep: str = ''
    iobj: int = 0
    iobjstr: str = ''
    argstr: str = ''
    args: List[Any] = None
    switches: List[str] = None

    def __post_init__(self):
        if self.args is None:
            self.args = []
        if self.switches is None:
            self.switches = []


# ============================================================
# EXCEPTIONS
# ============================================================


class ParseError(Exception):
    """
    Raised when command parsing fails.

    The message is typically displayed directly to the player
    (e.g. ``"Do what?"``).
    """
    pass


# ============================================================
# UTILITY FUNCTIONS
# ============================================================


def _extract_switches(verb_string: str):
    """
    Split a verb token on ``/`` to separate the verb name from switches.

    Builder and admin commands use ``/`` to attach modifier flags::

        @dig/teleport North = #42   -> verb='@dig', switches=['teleport']
        look/quiet                  -> verb='look', switches=['quiet']

    The bare ``/`` character (the eval shortcut) is special-cased so
    that it is never mistaken for a switch separator.

    Args:
        verb_string (str): The raw verb token, possibly containing
            slashes.

    Returns:
        tuple[str, list[str]]: A ``(verb_name, switches)`` pair.  If
        there are no slashes, ``switches`` is an empty list.

    Examples:
        >>> _extract_switches('look')
        ('look', [])
        >>> _extract_switches('@dig/teleport/quiet')
        ('@dig', ['teleport', 'quiet'])
        >>> _extract_switches('/')
        ('/', [])
    """
    if '/' not in verb_string or verb_string == '/':
        return verb_string, []
    parts = verb_string.split('/')
    # Filter out empty strings that arise from trailing slashes.
    return parts[0], [s for s in parts[1:] if s]


# ============================================================
# COMMAND PARSER
# ============================================================


class CommandParser:
    """
    Parses raw player input into a ``ParseResult`` suitable for verb
    dispatch.

    The parser is instantiated once per command.  It is **not** reusable
    across commands because it captures the player reference at
    construction time (the player's location and inventory may change
    between commands).

    This implements MOO's command parsing logic, including verb matching,
    object resolution, and preposition handling.

    Attributes:
        database (Database): The object database, used for object
            lookups during verb search and argument matching.
        player (MOOObject): The player object that typed the command.
            Used as the starting point for the verb search and as
            context for ``ObjectMatcher``.
    """

    def __init__(self, database, player: MOOObject):
        """
        Initialize command parser.

        Args:
            database (Database): The game database.
            player (MOOObject): The player issuing the command.
        """
        self.database = database
        self.player = player
        
    # --------------------------------------------------------
    # Public API
    # --------------------------------------------------------

    def parse(self, command: str) -> ParseResult:
        """
        Parse a raw command string into a ``ParseResult``.

        The method dispatches into one of three code paths depending on
        the first character of the input:

        - ``@`` or ``+`` prefix  -> ``_parse_prefixed_command()``
        - ``/`` prefix           -> treated as the eval shortcut
        - anything else          -> normal verb/argument parsing

        For normal commands the flow is:

        1. Split the first word as the verb (lower-cased), extract any
           ``/switches``.
        2. Search for the verb on the player, location, and nearby
           objects via ``_find_verb()``.
        3. Parse the remaining text into direct-object, preposition, and
           indirect-object via ``_parse_arguments()``.

        Args:
            command (str): Raw command string from the player.

        Returns:
            ParseResult: A fully-populated parse result.

        Raises:
            ParseError: If the command is empty or no matching verb can
                be found anywhere in the search path.

        Examples:
            >>> parser.parse("get lamp")
            ParseResult(verb='get', dobj=#123, dobjstr='lamp', ...)

            >>> parser.parse("put sword in bag")
            ParseResult(verb='put', dobj=#456, prep='in', iobj=#789, ...)

            >>> parser.parse("/2+2")
            ParseResult(verb='/', argstr='2+2', ...)
        """
        command = command.strip()
        if not command:
            raise ParseError("Empty command")

        # --- Prefixed commands (@create, +who, etc.) ---
        if command[0] in '@+':
            return self._parse_prefixed_command(command)

        # --- Slash eval shortcut (/expression) ---
        # The ``/`` verb allows quick Python evaluation without a space
        # between the slash and the expression.
        if command.startswith('/'):
            verb = '/'
            switches = []
            argstr = command[1:].strip()
        else:
            # --- Normal command ---
            parts = command.split(None, 1)
            verb, switches = _extract_switches(parts[0].lower())
            argstr = parts[1] if len(parts) > 1 else ''

        # Search for the verb definition in the environment
        verb_obj, verb_def = self._find_verb(verb)
        if not verb_def:
            raise ParseError("Do what?")

        # Split the argument string according to the verb's declared
        # dobj/prep/iobj specification.
        dobj, dobjstr, prep, iobj, iobjstr, args = self._parse_arguments(
            argstr, verb_def
        )

        return ParseResult(
            verb=verb,
            verb_obj=verb_obj,
            dobj=dobj,
            dobjstr=dobjstr,
            prep=prep,
            iobj=iobj,
            iobjstr=iobjstr,
            argstr=argstr,
            args=args,
            switches=switches,
        )
        
    # --------------------------------------------------------
    # Verb search
    # --------------------------------------------------------

    def _may_invoke(self, verb_def) -> bool:
        """This player against *verb_def*'s level -- see :func:`may_invoke`."""
        return may_invoke(self.player, verb_def)

    def _find_verb(self, verb_name: str) -> Tuple[int, Any]:
        """
        Find a verb in the player's environment that they may actually run.

        Wraps :meth:`_search_environment` with the gm-level check, so the
        level a verb declares gates dispatch the way ``hidden`` does.
        ``find_verb`` already refuses a hidden verb; ``auth`` sat beside
        it in the same VerbDef enforcing nothing.  Two places in the
        engine documented this check as though it existed: ``verb_loader``
        logs "gating dispatch at N" when it derives a level, and
        ``moo_builtins.shutdown`` explains that its guard has to live in
        the verb body because "the command parser's auth check does not
        cover a call that arrives through call_verb".  Both now describe
        the code.

        This does not replace the ``auth_level(pobj) < N`` guard a staff
        verb opens with, and is not meant to.  ``call_verb`` reaches a
        verb without going through the parser at all, deliberately --
        internal calls must not be subject to the caller's level.  What
        this adds is that a *typed* command cannot reach a verb the
        typist is not entitled to, so a verb whose guard was forgotten is
        not simply open.

        A refused verb is reported as not found rather than as refused --
        MOO's convention, and the same answer ``hidden`` gives.  The
        commands a player cannot use should not be discoverable by
        watching which ones deny them.
        """
        objnum, verb_def = self._search_environment(verb_name)
        if verb_def is not None and not self._may_invoke(verb_def):
            logger.debug(
                "Verb '%s' on #%s requires gm%s; player #%s is below it",
                verb_name, objnum, getattr(verb_def, 'auth', 0),
                self.player.objnum)
            return 0, None
        return objnum, verb_def

    def _search_environment(self, verb_name: str) -> Tuple[int, Any]:
        """
        Search the player's environment for a verb definition.

        The search follows the classic MOO priority order, which ensures
        that verbs "closer" to the player shadow those further away:

        1. **Player object** -- personal commands (e.g. ``@stats``).
        2. **Player's location** -- room-level commands (``look``,
           ``north``).
        3. **Objects in the room** -- verbs on other objects present in
           the same room (e.g. a vending machine's ``buy`` verb).
        4. **Player's inventory** -- verbs on carried objects (e.g. a
           wand's ``zap`` verb).

        Each ``find_verb()`` call walks the object's full inheritance
        chain, so a verb defined on a parent class is found even if the
        immediate object does not define it.

        Args:
            verb_name (str): The verb name to search for (already
                lower-cased).

        Returns:
            tuple[int, VerbDef | None]: ``(object_number, verb_def)``
            where ``object_number`` is the objnum of the object that
            *defines* the verb (which may be an ancestor), and
            ``verb_def`` is the ``VerbDef`` instance.  Returns
            ``(0, None)`` if the verb is not found anywhere.

        Notes:
            Exceptions from individual ``find_verb`` calls on room
            contents / inventory items are caught and silently ignored
            so that a single broken object does not prevent the player
            from typing any commands at all.
        """
        logger.debug(f"_find_verb searching for: {verb_name}")
        logger.debug(f"Player: #{self.player.objnum}, location: {self.player.location}")

        # 1. Check the player object itself
        objnum, verb_def = self.player.find_verb(verb_name, self.database)
        if verb_def:
            logger.debug(f"Found verb on player #{objnum}")
            return objnum, verb_def

        # 2. Check the player's location (room)
        location = self.player.location
        if location:
            logger.debug(f"Checking location #{location.objnum}")
            try:
                logger.debug(f"Location: {location.name}, has {len(location.verbs)} verbs")
                objnum, verb_def = location.find_verb(verb_name, self.database)
                if verb_def:
                    logger.debug(f"Found verb on location #{objnum}")
                    return objnum, verb_def
                else:
                    logger.debug(f"Verb '{verb_name}' not found on location")

                # 3. Check other objects in the same room (NPCs, furniture, etc.)
                for obj in location.contents:
                    # Skip the player themselves -- already checked above.
                    if obj.objnum == self.player.objnum:
                        continue
                    try:
                        objnum, verb_def = obj.find_verb(verb_name, self.database)
                        if verb_def:
                            return objnum, verb_def
                    except Exception:
                        pass
            except Exception as e:
                logger.error(f"Error checking location: {e}")
        else:
            logger.debug("Player has no location")

        # 4. Check the player's inventory (carried objects)
        for obj in self.player.contents:
            try:
                objnum, verb_def = obj.find_verb(verb_name, self.database)
                if verb_def:
                    return objnum, verb_def
            except Exception:
                pass

        logger.debug(f"Verb '{verb_name}' not found anywhere")
        return 0, None
        
    # --------------------------------------------------------
    # Argument parsing
    # --------------------------------------------------------

    def _parse_arguments(self, argstr: str, verb_def) -> Tuple:
        """
        Split the argument string according to the verb's declared specs.

        The verb definition carries three spec fields --
        ``dobj_spec``, ``prep_spec``, ``iobj_spec`` -- that tell the
        parser what structure to expect.  If ``dobj_spec`` is ``NONE``,
        the entire argstr is treated as a flat token list.  Otherwise
        we delegate to ``_extract_objects()`` to identify direct object,
        preposition, and indirect object.

        Args:
            argstr (str): Everything the player typed after the verb.
            verb_def: The matched ``VerbDef``.  Only its ``dobj_spec``,
                ``prep_spec``, and ``iobj_spec`` attributes are read
                (via ``getattr`` with safe defaults).

        Returns:
            tuple: ``(dobj, dobjstr, prep, iobj, iobjstr, args)`` where
            ``dobj`` and ``iobj`` are object numbers (or 0),
            ``dobjstr``/``iobjstr`` are the raw text, ``prep`` is the
            matched preposition string, and ``args`` is a convenience
            list of the non-empty object strings.
        """
        if not argstr:
            return 0, '', '', 0, '', []

        # Read the verb's argument specification with safe defaults.
        # Verbs that do not declare specs get permissive defaults so
        # that legacy verbs still work.
        dobj_spec = getattr(verb_def, 'dobj_spec', ArgSpec.ANY)
        prep_spec = getattr(verb_def, 'prep_spec', '')
        iobj_spec = getattr(verb_def, 'iobj_spec', ArgSpec.NONE)

        # Simple case: verb does not expect any object arguments.
        if dobj_spec == ArgSpec.NONE:
            return 0, '', '', 0, '', argstr.split()

        # Full parse: try to extract <dobj> [prep] [iobj]
        dobj, dobjstr, prep, iobj, iobjstr = self._extract_objects(
            argstr, dobj_spec, prep_spec, iobj_spec
        )

        # Build the convenience ``args`` list from non-empty strings.
        args = []
        if dobjstr:
            args.append(dobjstr)
        if iobjstr:
            args.append(iobjstr)

        return dobj, dobjstr, prep, iobj, iobjstr, args
        
    def _extract_objects(self, argstr: str, dobj_spec: ArgSpec,
                        prep_spec: str, iobj_spec: ArgSpec) -> Tuple:
        """
        Extract direct object, preposition, and indirect object from the
        argument string.

        This is the most intricate part of the parser.  It must handle
        several different syntactic patterns that players use:

        1. ``<dobj> <prep> <iobj>``  -- ``"put sword in bag"``
        2. ``<prep> <dobj>``         -- ``"look under rock"``
        3. ``<dobj>``                -- ``"get lamp"``
        4. ``<dobj>=<iobj>``         -- ``"#10=value"`` (property set)
        5. ``<dobj>?<iobj>``         -- ``"#10?prop"``  (property query)

        The method tries special prepositions (``=``, ``?``) first because
        they can appear glued to their operands without whitespace.  If
        none of the special prepositions match (or are not allowed by the
        verb's ``prep_spec``), it falls through to word-by-word scanning
        for standard prepositions (``in``, ``on``, ``to``, ``from``, etc.).

        Args:
            argstr (str): The argument portion of the command.
            dobj_spec (ArgSpec): What the verb expects in the direct-
                object slot.
            prep_spec (str): Slash-separated list of allowed prepositions
                (e.g. ``"in/on/into"``), the special value ``"any"``
                (accept any preposition), or ``""`` (no preposition
                expected).
            iobj_spec (ArgSpec): What the verb expects in the indirect-
                object slot.

        Returns:
            tuple: ``(dobj, dobjstr, prep, iobj, iobjstr)``
        """
        from .globals import SPECIAL_PREPOSITIONS
        import re

        # --- Special preposition scan (= and ?) ---
        # These can appear without surrounding whitespace, so we cannot
        # rely on word splitting.  We check them first because they are
        # unambiguous single-character tokens.
        special_prep_pattern = r'([=?])'

        if any(sp in argstr for sp in SPECIAL_PREPOSITIONS):
            for special in SPECIAL_PREPOSITIONS:
                if special in argstr:
                    parts = argstr.split(special, 1)
                    if len(parts) == 2:
                        dobjstr = parts[0].strip()
                        iobjstr = parts[1].strip()
                        prep = special

                        # Attempt to resolve the text to in-game objects.
                        dobj = 0
                        if dobjstr and dobj_spec != ArgSpec.NONE:
                            dobj = self._match_object(dobjstr, dobj_spec)

                        iobj = 0
                        if iobjstr and iobj_spec != ArgSpec.NONE:
                            iobj = self._match_object(iobjstr, iobj_spec)

                        return dobj, dobjstr, prep, iobj, iobjstr

        # --- Standard preposition scan (word-by-word) ---
        prep = ''
        prep_pos = -1

        if prep_spec:
            words = argstr.split()
            if not words:
                return 0, '', '', 0, ''

            # Check if the *first* word is a preposition.  This handles
            # the ``<prep> <dobj>`` pattern (e.g. ``look under rock``),
            # where the preposition precedes the direct object.
            first_word_prep = match_preposition(words[0])
            if first_word_prep and (prep_spec == 'any' or first_word_prep in prep_spec.split('/')):
                prep = first_word_prep
                prep_pos = 0
            elif iobj_spec != ArgSpec.NONE:
                # Only scan for a *middle* preposition when the verb
                # actually declares an indirect-object slot.  This
                # avoids false positives where a common word like "in"
                # appears inside a direct-object phrase.
                for i, word in enumerate(words):
                    matched_prep = match_preposition(word)
                    if matched_prep:
                        if prep_spec == 'any' or matched_prep in prep_spec.split('/'):
                            prep = matched_prep
                            prep_pos = i
                            break

        # --- Split the string around the preposition ---
        if prep_pos >= 0:
            words = argstr.split()

            if prep_pos == 0:
                # Preposition is first: everything after it is the dobj.
                dobjstr = ' '.join(words[1:])
                iobjstr = ''
            else:
                # Normal ``<dobj> <prep> <iobj>`` layout.
                dobjstr = ' '.join(words[:prep_pos])
                iobjstr = ' '.join(words[prep_pos + 1:])
        else:
            # No preposition found -- entire argstr is the direct object.
            dobjstr = argstr
            iobjstr = ''

        # --- Object matching ---
        # Try to resolve text references to actual database objects.
        dobj = 0
        if dobjstr and dobj_spec != ArgSpec.NONE:
            dobj = self._match_object(dobjstr, dobj_spec)

        iobj = 0
        if iobjstr and iobj_spec != ArgSpec.NONE:
            iobj = self._match_object(iobjstr, iobj_spec)

        return dobj, dobjstr, prep, iobj, iobjstr
        
    # --------------------------------------------------------
    # Object matching
    # --------------------------------------------------------

    def _match_object(self, name: str, spec: ArgSpec) -> int:
        """
        Attempt to resolve a textual reference to a database object.

        The behaviour depends on the ``ArgSpec``:

        - ``NONE`` -- always returns 0 (no match attempted).
        - ``ANY``  -- tries ``ObjectMatcher`` which checks ``#num``
          references, ``"me"``, ``"here"``, and name/alias matches in
          the player's vicinity.  If no object is found, returns 0
          and the caller keeps the raw text as a string argument.
        - ``THIS`` -- resolution is deferred to verb execution time (the
          verb executor checks whether the resolved object is the same
          as ``this``), so we return 0 here.

        Args:
            name (str): The text the player typed in the object position
                (e.g. ``"sword"``, ``"#42"``, ``"me"``).
            spec (ArgSpec): The verb's declared specification for this
                object slot.

        Returns:
            int: The matched object number, or ``0`` if no match was
            found (or matching was not appropriate for this spec).
        """
        if spec == ArgSpec.NONE:
            return 0

        if spec == ArgSpec.ANY:
            # Attempt a match but gracefully fall back to string-only.
            try:
                matcher = ObjectMatcher(self.database, self.player)
                obj = matcher.match(name)
                return obj.objnum
            except MatchError:
                return 0

        if spec == ArgSpec.THIS:
            # Deferred to verb execution -- the executor validates
            # that the resolved object matches ``this``.
            return 0

        return 0
        
    # --------------------------------------------------------
    # Prefixed command parsing
    # --------------------------------------------------------

    def _parse_prefixed_command(self, command: str) -> ParseResult:
        """
        Parse a command that starts with ``@`` or ``+``.

        Prefixed commands are typically builder/admin commands (``@dig``,
        ``@create``) or system channels (``+public``, ``+staff``).

        The parser finds the verb on the player (or inherited parent),
        then applies the same argument parsing (preposition splitting
        and object resolution) used for normal commands.

        Switch extraction still applies::

            @addverb/quiet sword:stab  ->  verb='@addverb', switches=['quiet']

        Args:
            command (str): The full command string, including the leading
                ``@`` or ``+`` character.

        Returns:
            ParseResult: A result with the prefix baked into ``verb``,
            ``verb_obj`` set to the player or defining object, and
            ``argstr`` / ``args`` / ``dobj`` / ``prep`` / ``iobj``
            populated from the argument string.
        """
        # Capture and strip the prefix character.
        prefix = command[0]
        command = command[1:]
        parts = command.split(None, 1)
        raw_verb = parts[0].lower()
        argstr = parts[1] if len(parts) > 1 else ''

        # Extract switches: @addverb/quiet -> verb='addverb', switches=['quiet']
        verb, switches = _extract_switches(raw_verb)
        full_verb = f'{prefix}{verb}'

        # Search for the verb definition on the player (walks inheritance)
        verb_obj, verb_def = self._find_verb(full_verb)
        if not verb_def:
            # Verb not found -- return minimal result; the server will
            # report "Do what?" when it also fails to find the verb.
            return ParseResult(
                verb=full_verb,
                verb_obj=self.player.objnum,
                argstr=argstr,
                args=argstr.split() if argstr else [],
                switches=switches,
            )

        # Parse arguments the same way normal commands do.
        dobj, dobjstr, prep, iobj, iobjstr, args = self._parse_arguments(
            argstr, verb_def
        )

        return ParseResult(
            verb=full_verb,
            verb_obj=verb_obj or self.player.objnum,
            dobj=dobj,
            dobjstr=dobjstr,
            prep=prep,
            iobj=iobj,
            iobjstr=iobjstr,
            argstr=argstr,
            args=args,
            switches=switches,
        )


# ============================================================
# STANDALONE UTILITIES
# ============================================================


def may_invoke(player, verb_def) -> bool:
    """
    Whether *player* clears the gm level *verb_def* requires.

    The rule is ``auth_level(player) >= verb_def.auth`` -- the level the
    verb asks for, not a fixed number.  A verb that asks for nothing
    (``auth`` 0, the default) is open to everyone.

    Lives here rather than on the parser because the parser is not the
    only place a typed command is resolved.  ``@`` and ``+`` commands
    take a different route: when the parser cannot find one it returns a
    minimal result and lets the server look the verb up again, so a check
    that existed only in the parser would cover ``eval`` and miss
    ``@dig`` -- which is most of the staff commands there are.

    Never raises.  A player object with no ``auth`` reads as level 0,
    which is what an ordinary character is; anything that goes wrong
    while establishing a level refuses, because a staff verb is the
    wrong place to fail open.
    """
    required = getattr(verb_def, 'auth', 0) or 0
    if required <= 0:
        return True
    try:
        from .builtins import auth_level
        return auth_level(player) >= required
    except Exception:
        return False


def split_command_line(line: str) -> List[str]:
    """
    Split a command line into tokens, respecting quoted strings.

    This is a lightweight alternative to ``shlex.split()`` that handles
    both single and double quotes without backslash escaping.  Quoted
    regions are preserved as single tokens with the quote characters
    stripped.  Mismatched quotes are tolerated -- the unclosed quote
    simply runs to end-of-string.

    Args:
        line (str): The raw command line to tokenise.

    Returns:
        list[str]: A list of tokens with quotes removed.

    Examples:
        >>> split_command_line('say hello world')
        ['say', 'hello', 'world']

        >>> split_command_line('say "hello world"')
        ['say', 'hello world']

        >>> split_command_line("give 'magic sword' to wizard")
        ['give', 'magic sword', 'to', 'wizard']

    Notes:
        Unlike ``shlex``, this function does **not** support escape
        characters (``\\``).  A backslash inside quotes is kept
        literally.  This matches LambdaMOO's original tokeniser
        behaviour.
    """
    tokens = []
    current = []
    in_quote = False
    quote_char = None

    for char in line:
        if char in ('"', "'"):
            if in_quote:
                if char == quote_char:
                    # Matching close quote -- end the quoted region.
                    in_quote = False
                    quote_char = None
                else:
                    # Different quote character inside quotes -- literal.
                    current.append(char)
            else:
                # Opening quote -- start a quoted region.
                in_quote = True
                quote_char = char
        elif char.isspace() and not in_quote:
            # Whitespace outside quotes ends the current token.
            if current:
                tokens.append(''.join(current))
                current = []
        else:
            current.append(char)

    # Flush any remaining token (handles unclosed quotes gracefully).
    if current:
        tokens.append(''.join(current))

    return tokens
