"""
MegaMOO Match Utilities

Pure-function matching library for resolving player input to game objects.
No classes, no database dependency -- just strings in, answers out.

This module is the core of MegaMOO's natural-language object resolution.
When a player types ``get the 2nd blue sword``, the parser needs to figure
out which actual game object they mean.  This module provides the matching
pipeline that makes that possible.

Matching Hierarchy
------------------
The high-level matchers (``bmatch``, ``pmatch``) resolve input in this
order:

1. **Possessive prefix**: ``my sword`` restricts the search to the
   player's inventory only.
2. **Keywords**: ``me`` (the player object), ``here`` (the player's
   current room/location).
3. **Object references**: ``#3`` (direct database reference by objnum),
   ``$name`` (system constant lookup via object #0's properties).
4. **Name + adjective + ordinal matching** against a candidate list,
   using the functions ``match()`` and ``match_all()``.

Name Matching Details
---------------------
The ``match()`` function breaks the player's input into tokens and
interprets them as follows:

- **Articles** (``the``, ``a``, ``an``, ``some``) are stripped from the
  front of the input.
- **Ordinals** at the start (``2nd``, ``third``, ``3``) select the Nth
  match from the candidate list rather than the first.
- The **last token** is treated as the noun and matched against each
  candidate's ``name``, ``aliases``, and ``noun`` property using prefix
  matching (minimum 2 characters).
- All **preceding tokens** are treated as adjectives and must appear in
  order within the candidate's name (or in its ``adjectives`` property
  list).

Examples::

    "sword"           -> noun="sword", adjectives=[], ordinal=0
    "blue sword"      -> noun="sword", adjectives=["blue"], ordinal=0
    "2nd blue sword"  -> noun="sword", adjectives=["blue"], ordinal=1
    "the big red ball" -> noun="ball", adjectives=["big", "red"], ordinal=0

Preposition Matching
--------------------
The module also provides ``prep_match()`` and ``split_on_prep()`` for
parsing command strings that contain prepositions (e.g. ``put sword in
chest``).  These are used by the command parser to separate the direct
object, preposition, and indirect object.

Architecture
------------
All functions in this module are pure (no side effects, no global state).
They take strings and object lists as input and return results.  The
``Database`` is only needed for ``#N`` dbref resolution and is passed
explicitly or discovered via ``pobj._database``.

Copyright (c) 2026
License: MIT
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple, Union

if TYPE_CHECKING:
    from .objects import MOOObject
    from .database import Database


# ============================================================================
# CONSTANTS -- Ordinals, articles, and lookup tables
# ============================================================================

#: Word ordinals mapped to 0-based indices.  Covers "first" through
#: "twentieth", which handles the vast majority of player input.
_ORDINAL_WORDS = {
    'first': 0, 'second': 1, 'third': 2, 'fourth': 3, 'fifth': 4,
    'sixth': 5, 'seventh': 6, 'eighth': 7, 'ninth': 8, 'tenth': 9,
    'eleventh': 10, 'twelfth': 11, 'thirteenth': 12, 'fourteenth': 13,
    'fifteenth': 14, 'sixteenth': 15, 'seventeenth': 16, 'eighteenth': 17,
    'nineteenth': 18, 'twentieth': 19,
}

#: Two-letter suffixes that, when appended to a number, form a numeric
#: ordinal (1st, 2nd, 3rd, 4th, 21st, 22nd, etc.).
_ORDINAL_SUFFIXES = frozenset({'st', 'nd', 'rd', 'th'})

#: English articles that are stripped from the beginning of player input
#: before matching.  This allows players to type "get the sword" or
#: "look at a painting" naturally.
_ARTICLES = frozenset({'the', 'a', 'an', 'some'})


# ============================================================================
# LOW-LEVEL HELPERS -- Parsing and individual-object matching
# ============================================================================

def parse_ordinal(word: str) -> Optional[int]:
    """
    Parse an ordinal token into a 0-based index.

    Supports three formats:

    - **Word ordinals**: ``first`` through ``twentieth`` (looked up in
      ``_ORDINAL_WORDS``).
    - **Numeric ordinals**: A bare integer followed by a two-letter
      suffix: ``1st``, ``2nd``, ``3rd``, ``4th``, ``21st``, etc.
    - **Bare integers**: ``1``, ``2``, ``5`` -- treated as 1-based
      ordinals and converted to 0-based.

    Args:
        word (str): The token to parse (e.g. ``"third"``, ``"2nd"``,
            ``"5"``).

    Returns:
        int or None: The 0-based index if *word* is a valid ordinal,
        or ``None`` if it is not an ordinal at all.

    Examples::

        parse_ordinal('third')  # => 2  (0-based)
        parse_ordinal('2nd')    # => 1
        parse_ordinal('5')      # => 4
        parse_ordinal('sword')  # => None
    """
    low = word.casefold()

    # Word ordinals: "first" -> 0, "second" -> 1, etc.
    idx = _ORDINAL_WORDS.get(low)
    if idx is not None:
        return idx

    # Numeric suffix ordinals: "1st" -> 0, "2nd" -> 1, "3rd" -> 2, etc.
    if len(low) > 2 and low[-2:] in _ORDINAL_SUFFIXES and low[:-2].isdigit():
        return int(low[:-2]) - 1

    # Bare integer: "1" -> 0, "2" -> 1, etc.
    if low.isdigit():
        return int(low) - 1

    return None


def strip_articles(text: str) -> str:
    """
    Remove a leading article from the beginning of *text*.

    If the first word is one of ``the``, ``a``, ``an``, or ``some``
    (case-insensitive), it is removed along with the following space.
    Only the *first* article is stripped; subsequent articles in the
    string are left alone.

    If no article is found, or the text is a single word, the original
    string is returned unchanged.

    Args:
        text (str): The input text, typically raw player input.

    Returns:
        str: The text with the leading article removed, if any.

    Examples::

        strip_articles('the blue sword')  # => 'blue sword'
        strip_articles('a ring')          # => 'ring'
        strip_articles('anvil')           # => 'anvil'
        strip_articles('the')             # => 'the'  (no word after article)
    """
    first_space = text.find(' ')
    if first_space == -1:
        # Single word -- nothing to strip
        return text
    first_word = text[:first_space].casefold()
    if first_word in _ARTICLES:
        return text[first_space + 1:]
    return text


def name_match(obj: MOOObject, token: str) -> bool:
    """
    Check whether *token* matches *obj* by name or alias (prefix match).

    The token is compared case-insensitively against:

    1. Each non-article word in ``obj.name`` (e.g. for an object named
       "a silver sword", the words "silver" and "sword" are checked).
    2. Each entry in ``obj.aliases`` (a list of alternative names).
    3. The ``obj.noun`` property (the atomic/base name, e.g. "sword").

    Matching rules:
        - Tokens of 2+ characters use prefix matching (e.g. "swo"
          matches "sword").
        - Single-character tokens require an exact full-word match.

    Args:
        obj (MOOObject): The candidate game object.
        token (str): The search token from player input (the noun part).

    Returns:
        bool: ``True`` if the token matches the object, ``False``
        otherwise.

    Examples::

        name_match(sword_obj, 'swo')    # True  (prefix of "sword")
        name_match(sword_obj, 'sword')  # True  (exact match)
        name_match(sword_obj, 'sh')     # False (no word starts with "sh")
    """
    tok = token.casefold()
    # Single-char tokens need exact match; 2+ chars allow prefix matching.
    # Tokens shorter than 1 char never match.
    min_prefix = 1 if len(tok) <= 1 else 2

    if len(tok) < min_prefix:
        return False

    obj_name = obj.name.casefold()

    # Check each non-article word in the object's name
    for word in obj_name.split():
        if word in _ARTICLES:
            continue
        if word.startswith(tok):
            return True

    # Check alias list (alternative names for the object)
    for alias in obj.aliases:
        if alias.casefold().startswith(tok):
            return True

    # Check the 'noun' property (the core/atomic name, e.g. "sword")
    noun = obj.noun
    if noun and noun.casefold().startswith(tok):
        return True

    return False


def adj_match(adjectives: List[str], obj: MOOObject) -> bool:
    """
    Check whether all given adjectives appear in *obj*'s name, in order.

    This is used to disambiguate between multiple objects that share the
    same noun.  For example, if a room contains "a big blue ball" and
    "a small red ball", the adjectives ["blue"] would match the first
    but not the second.

    The matching works in two passes:

    **Pass 1 -- Name scanning (fast path)**:
        Each adjective is searched for as a whole word in ``obj.name``,
        in order.  "In order" means each adjective must appear *after*
        the previous one in the name string.  Word boundaries are
        enforced (so "blue" does not match inside "blueberry").

    **Pass 2 -- Property fallback**:
        If name scanning fails, the function checks for an ``adjectives``
        property on the object (a list of strings).  Adjectives are
        matched by prefix against this list, also in order.

    An empty adjective list always matches (returns ``True``).

    Args:
        adjectives (list of str): Adjective tokens from player input,
            in the order they were typed.
        obj (MOOObject): The candidate game object.

    Returns:
        bool: ``True`` if all adjectives match in order, ``False``
        otherwise.

    Examples::

        adj_match(['blue'], obj_named_"a big blue ball")      # True
        adj_match(['big', 'blue'], obj_named_"a big blue ball")  # True
        adj_match(['blue', 'big'], obj_named_"a big blue ball")  # False (wrong order)
    """
    if not adjectives:
        return True

    title = obj.name.casefold()

    # --- Pass 1: Ordered substring matching against the full name ---
    pos = 0
    for adj in adjectives:
        adj_low = adj.casefold()
        # Find the adjective starting at 'pos' (after previous matches)
        idx = title.find(adj_low, pos)
        if idx == -1:
            break
        # Enforce word boundary: adjective must be at start of string
        # or preceded by a space
        if idx > 0 and title[idx - 1] != ' ':
            idx = title.find(' ' + adj_low, pos)
            if idx == -1:
                break
            idx += 1  # skip the leading space
        # Advance past this adjective for the next search
        pos = idx + len(adj_low)
    else:
        # The for-loop completed without breaking -- all adjectives matched
        return True

    # --- Pass 2: Fallback to the 'adjectives' property list ---
    props = obj.properties
    if 'adjectives' in props:
        obj_adjs = props['adjectives'].value
        if isinstance(obj_adjs, (list, tuple)):
            obj_adjs_low = [a.casefold() for a in obj_adjs]
            last_idx = -1
            for adj in adjectives:
                adj_low = adj.casefold()
                # Find this adjective in the property list after last_idx
                found = False
                for i in range(last_idx + 1, len(obj_adjs_low)):
                    if obj_adjs_low[i].startswith(adj_low):
                        last_idx = i
                        found = True
                        break
                if not found:
                    return False
            return True

    return False


def smatch(target: str, query: str, minlen: int = 0) -> bool:
    """
    Simple partial string match: does *target* start with *query*?

    This is a case-insensitive prefix match with an optional minimum
    length requirement.  It is used for matching verb names, prepositions,
    and other short strings where full ``name_match`` logic is overkill.

    Args:
        target (str): The full string to match against (e.g. a verb name).
        query (str): The prefix to test (e.g. player input).
        minlen (int, optional): Minimum required length of *query*.
            If *query* is shorter than this, the match fails.  Useful
            for preventing overly short abbreviations.  Defaults to 0
            (no minimum).

    Returns:
        bool: ``True`` if *target* starts with *query* (case-insensitive)
        and *query* meets the minimum length, ``False`` otherwise.

    Examples::

        smatch('underneath', 'under')          # True
        smatch('underneath', 'un', minlen=3)   # False (too short)
        smatch('look', 'LOOK')                 # True (case-insensitive)
    """
    if minlen and len(query) < minlen:
        return False
    return target.casefold().startswith(query.casefold())


# ============================================================================
# OBJECT RESOLUTION -- Keywords, dbrefs, and system constants
# ============================================================================

def _resolve_db(pobj: MOOObject, db: Database = None) -> Optional[Database]:
    """
    Obtain a Database reference from an explicit parameter or the player object.

    This helper centralises database discovery so that callers can either
    pass ``db`` explicitly or let it be found via ``pobj._database``
    (which is set when the object is loaded from the database).

    Args:
        pobj (MOOObject): The player object (may have ``_database`` set).
        db (Database, optional): An explicit database reference.  If
            provided, this takes priority.

    Returns:
        Database or None: The resolved database, or ``None`` if neither
        source provides one.
    """
    if db is not None:
        return db
    return getattr(pobj, '_database', None)


def omatch(inp: str, pobj: MOOObject, db: Database = None) -> Optional[MOOObject]:
    """
    Resolve a keyword or object reference to a game object.

    This function handles the "special" input forms that bypass normal
    name matching:

    - ``me`` -- Returns the player object (*pobj*) itself.
    - ``here`` -- Returns the player's current location (``pobj.location``).
    - ``#N`` -- Direct database lookup by object number (requires a
      ``Database`` instance).
    - ``$name`` -- System constant lookup.  Reads the property *name*
      from object #0 (the system object) and resolves it to a game
      object.  For example, ``$room_builder`` might resolve to object
      #47.

    Args:
        inp (str): The raw input string to resolve.
        pobj (MOOObject): The acting player object.
        db (Database, optional): Database for ``#N`` and ``$name``
            lookups.  If not provided, ``pobj._database`` is used.

    Returns:
        MOOObject or None: The resolved object, or ``None`` if the
        input does not match any keyword or reference pattern.

    Note:
        This function returns ``None`` for ordinary object names like
        ``"sword"`` -- those are handled by ``match()`` instead.
    """
    low = inp.casefold().strip()

    # --- Keyword: "me" ---
    if low == 'me':
        return pobj

    # --- Keyword: "here" ---
    if low == 'here':
        return pobj.location  # None if the player is nowhere

    # --- Direct dbref: "#N" (e.g. "#3", "#17") ---
    if low.startswith('#') and low[1:].isdigit():
        rdb = _resolve_db(pobj, db)
        if rdb:
            try:
                return rdb.get_object(int(low[1:]))
            except (KeyError, Exception):
                return None
        return None

    # --- System constant: "$name" (e.g. "$room_builder") ---
    # Looks up a property on object #0 (the system/root object) and
    # resolves it to a game object.
    if low.startswith('$') and len(low) > 1:
        rdb = _resolve_db(pobj, db)
        if not rdb:
            return None
        prop_name = low[1:]
        try:
            sys_obj = rdb.get_object(0)
            val = getattr(sys_obj, prop_name, None)
            if val is None:
                return None
            # MOOObject.__getattr__ auto-resolves "#N" string values to
            # live MOOObject instances, so check if it's already resolved
            if hasattr(val, 'objnum'):
                return val
            # If it's a bare integer, treat it as an object number
            if isinstance(val, int):
                return rdb.get_object(val)
        except (KeyError, Exception):
            return None
        return None

    # Not a keyword or reference -- return None so the caller can
    # fall through to name-based matching
    return None


# ============================================================================
# NAME-BASED MATCHING -- Match input against candidate object lists
# ============================================================================

def match(inp: str, candidates: Sequence[MOOObject],
          ordinal: int = 0) -> Optional[MOOObject]:
    """
    Match a player's input string against a list of candidate objects.

    This is the core matching function.  It parses the input into
    structured components (ordinal, adjectives, noun) and searches
    the candidate list for the Nth matching object.

    Parsing steps:
        1. Strip leading articles (``the``, ``a``, ``an``, ``some``).
        2. If the first remaining token is an ordinal (``2nd``,
           ``third``, ``3``), consume it and set the ordinal index.
        3. The last remaining token becomes the **noun**.
        4. All tokens between the ordinal and the noun become
           **adjectives**.

    Matching:
        Each candidate is tested with ``name_match()`` (noun) and
        ``adj_match()`` (adjectives).  The function returns the
        *ordinal*-th match (0-based), or ``None`` if there are
        not enough matches.

    Args:
        inp (str): Player input (e.g. ``"big blue sword"``,
            ``"2nd ring"``, ``"the golden key"``).
        candidates (Sequence[MOOObject]): The list of game objects to
            search.  Typically ``room.contents + player.contents``.
        ordinal (int, optional): A 0-based index override.  If the
            input itself contains an ordinal, that takes priority.
            Defaults to 0 (return the first match).

    Returns:
        MOOObject or None: The matching object, or ``None`` if no match
        was found.

    Examples::

        match("sword", room.contents)
        # Returns the first object whose name/alias matches "sword"

        match("2nd blue sword", room.contents)
        # Returns the second object matching noun="sword" + adj=["blue"]

        match("silver ring", pobj.contents)
        # Returns the first "ring" with "silver" in its name
    """
    if not inp or not candidates:
        return None

    tokens = strip_articles(inp.strip()).split()
    if not tokens:
        return None

    # Check for a leading ordinal (e.g. "2nd", "third", "3")
    ord_idx = parse_ordinal(tokens[0])
    if ord_idx is not None:
        ordinal = ord_idx
        tokens = tokens[1:]
        if not tokens:
            return None  # ordinal with no noun (e.g. just "2nd")

    # The last token is the noun; everything before it is adjectives
    noun = tokens[-1]
    adjectives = tokens[:-1]

    # Iterate candidates, counting matches until we reach the desired ordinal
    count = 0
    for obj in candidates:
        if name_match(obj, noun) and adj_match(adjectives, obj):
            if count == ordinal:
                return obj
            count += 1

    return None


def match_all(inp: str, candidates: Sequence[MOOObject]) -> List[MOOObject]:
    """
    Return all objects matching the input, ignoring any ordinal.

    This is the multi-match variant of :func:`match`.  It returns every
    candidate that matches the noun and adjective criteria, regardless
    of ordinals.  Useful for commands like ``get all sword`` or for
    building disambiguation prompts.

    Args:
        inp (str): Player input (e.g. ``"blue sword"``).
        candidates (Sequence[MOOObject]): Objects to search.

    Returns:
        list[MOOObject]: All matching objects (may be empty).
    """
    if not inp or not candidates:
        return []

    tokens = strip_articles(inp.strip()).split()
    if not tokens:
        return []

    # Skip ordinal if present (we want ALL matches, not the Nth)
    if parse_ordinal(tokens[0]) is not None:
        tokens = tokens[1:]
        if not tokens:
            return []

    noun = tokens[-1]
    adjectives = tokens[:-1]

    return [obj for obj in candidates
            if name_match(obj, noun) and adj_match(adjectives, obj)]


# ============================================================================
# HIGH-LEVEL CONVENIENCE MATCHERS
# ============================================================================
# These are the primary entry points for verb code.  They combine keyword
# resolution (omatch) with name-based matching (match) and handle the
# "my <X>" possessive prefix.

def bmatch(inp: str, pobj: MOOObject, candidates: Sequence[MOOObject],
           db: Database = None) -> Optional[MOOObject]:
    """
    Broad match -- the standard entry point for verb code.

    This is the function most verbs call to resolve a player's input
    to a game object.  It tries multiple resolution strategies in order:

    Resolution order:
        1. **Possessive**: ``my <X>`` restricts the search to the
           player's own inventory (``pobj.contents``), ignoring the
           *candidates* list entirely.
        2. **Keywords / dbrefs / constants**: Delegates to :func:`omatch`
           to handle ``me``, ``here``, ``#N``, and ``$name``.
        3. **Name matching**: Falls through to :func:`match` against
           the provided *candidates* list.

    Args:
        inp (str): Raw player input (e.g. ``"my blue sword"``,
            ``"#3"``, ``"the golden key"``).
        pobj (MOOObject): The acting player object.
        candidates (Sequence[MOOObject]): Objects to search for
            name-based matching.  Typically built from the contents
            of the player's location and/or inventory.
        db (Database, optional): Database for ``#N`` dbref resolution.
            If not provided, ``pobj._database`` is used as a fallback.

    Returns:
        MOOObject or None: The resolved object, or ``None`` if nothing
        matched.

    Examples::

        # Search room + inventory for "sword"
        bmatch("sword", pobj, pobj.contents + pobj.location.contents)

        # Search inside a specific container
        bmatch("gem", pobj, chest.contents)

        # Force inventory-only search
        bmatch("my key", pobj, [])  # 'my' prefix ignores candidates list
    """
    if not inp:
        return None

    text = inp.strip()

    # --- "my <X>" -- restrict to player's own inventory ---
    if text.casefold().startswith('my '):
        text = text[3:].strip()
        return match(text, pobj.contents) if text else None

    # --- Keywords / dbrefs / system constants ---
    obj = omatch(text, pobj, db)
    if obj is not None:
        return obj

    # --- Name-based matching against the candidate list ---
    return match(text, candidates)


def pmatch(inp: str, pobj: MOOObject,
           candidates: Sequence[MOOObject]) -> Optional[MOOObject]:
    """
    Player/restricted match -- like :func:`bmatch` but without dbref support.

    This matcher is intended for use in non-wizard commands where players
    should not be able to use ``#N`` syntax to reference arbitrary
    objects.  It supports ``me``, ``here``, ``my <X>``, and name
    matching, but NOT ``#N`` or ``$name``.

    The ``my <X>`` handling differs from :func:`bmatch`:  rather than
    searching ``pobj.contents`` directly, it filters the *candidates*
    list to only include objects whose location is *pobj*.  This is
    useful when the candidates list has already been curated.

    Args:
        inp (str): Raw player input.
        pobj (MOOObject): The acting player object.
        candidates (Sequence[MOOObject]): Objects to search.

    Returns:
        MOOObject or None: The resolved object, or ``None``.
    """
    if not inp:
        return None

    text = inp.strip()

    # --- "my <X>" -- filter candidates to player's possessions ---
    if text.casefold().startswith('my '):
        text = text[3:].strip()
        if not text:
            return None
        # Filter candidates to only those located inside the player
        my_items = [obj for obj in candidates
                    if getattr(getattr(obj, 'location', None), 'objnum', None) == pobj.objnum]
        return match(text, my_items) if my_items else None

    # --- Keywords only: "me" and "here" (no #N or $name) ---
    low = text.casefold()
    if low == 'me':
        return pobj
    if low == 'here':
        return pobj.location

    # --- Name-based matching ---
    return match(text, candidates)


# ============================================================================
# PREPOSITION MATCHING
# ============================================================================
# These functions are used by the command parser to identify prepositions
# in player input and split commands around them.  For example, "put sword
# in chest" is split into dobj="sword", prep="in", iobj="chest".
#
# The canonical preposition list and aliases are defined in moo.globals
# (imported lazily to avoid circular imports at module level).

def prep_match(word: str) -> Optional[str]:
    """
    Match a word to a canonical preposition.

    Checks *word* against all known preposition aliases (defined in
    ``moo.globals.PREPOSITIONS``).  Aliases can be plain strings
    (exact match only) or tuples ``(word, min_chars)`` for prefix
    matching down to *min_chars* characters.

    Args:
        word (str): The word to look up (e.g. ``"in"``, ``"thru"``,
            ``"beh"``).

    Returns:
        str or None: The canonical preposition form (e.g. ``"in"``,
        ``"on"``, ``"behind"``), or ``None`` if no match is found.

    Examples::

        prep_match('in')     # => 'in'
        prep_match('onto')   # => 'on'
        prep_match('thru')   # => 'through'
        prep_match('beh')    # => 'behind'
        prep_match('sword')  # => None
    """
    # Lazy import to avoid circular dependency with moo.globals
    from .globals import PREPOSITIONS

    low = word.casefold()
    for canonical, aliases in PREPOSITIONS.items():
        for alias in aliases:
            if isinstance(alias, tuple):
                full, min_chars = alias
                full_lower = full.lower()
                if low == full_lower:
                    return canonical
                if (len(low) >= min_chars
                        and full_lower.startswith(low)):
                    return canonical
            else:
                if alias.lower() == low:
                    return canonical
    return None


def split_on_prep(text: str) -> Tuple[str, Optional[str], str]:
    """
    Split a command string on the first recognised preposition.

    Scans the words in *text* left to right, looking for a word that
    matches a known preposition via :func:`prep_match`.  Returns a
    3-tuple of ``(before, preposition, after)`` where:

    - *before* is the text before the preposition (the direct object).
    - *preposition* is the canonical form of the matched preposition.
    - *after* is the text after the preposition (the indirect object).

    If no preposition is found, returns ``(text, None, '')``.

    Args:
        text (str): The command string to split (e.g. ``"put sword in
            chest"``).

    Returns:
        tuple[str, str|None, str]: A 3-tuple of
        ``(before, preposition, after)``.

    Examples::

        split_on_prep('put sword in chest')
        # => ('put sword', 'in', 'chest')

        split_on_prep('look at painting')
        # => ('look', 'at', 'painting')

        split_on_prep('get sword')
        # => ('get sword', None, '')
    """
    words = text.split()
    for i, word in enumerate(words):
        canonical = prep_match(word)
        if canonical is not None:
            before = ' '.join(words[:i])
            after = ' '.join(words[i + 1:])
            return before, canonical, after
    # No preposition found
    return text, None, ''
