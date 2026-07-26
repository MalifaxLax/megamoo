"""
MegaMOO Search Engine
=====================

Provides an optimised global object search facility, inspired by Evennia's
``search_object()`` and adapted for MegaMOO's prototype-delegation object
model.

Conceptual Overview
-------------------
In a MOO, players and verbs frequently need to locate objects by name,
alias, dbref, parent chain, location, flags, or arbitrary property values.
Naive linear scans become prohibitively expensive as the database grows,
so this module maintains an **inverted word index** that maps lowercased
tokens to sets of object numbers, giving O(1) lookup per token.

The index is rebuilt lazily: every mutating operation in the database
increments ``db._mutation_gen``, and the :class:`SearchIndex` compares its
own generation counter before each query.  A full rebuild of 10 000 objects
takes roughly 10 ms, so the lazy strategy is both simple and fast enough.

Features
--------
* **Inverted word index** on noun, display-name words, and aliases.
* **Generation-based lazy rebuild** via ``db._mutation_gen``.
* **Rich filtering**: ``isa`` (parent-chain / typeclass), ``location``,
  ``flag``, ``property`` existence and value.
* **Exact and prefix matching** for flexible in-game searches.
* **Candidate-scoped search** -- search within a pre-filtered list.
* **Callable from verb code** as ``search(...)`` and ``find(...)``.

Usage in Verb Code
------------------
::

    # Find all swords in the game
    results = search('sword')

    # Find by dbref
    results = search('#76')

    # Exact match only
    results = search('Warrior', exact=True)

    # Filter by parent chain (typeclass equivalent)
    results = search('sword', isa=35)          # descendants of #35
    results = search('sword', isa=db.get_object(35))

    # Filter by location
    results = search('key', location=this)

    # Filter by flag
    results = search(flag='player')            # all players

    # Filter by property existence or value
    results = search(property='label')                        # has property
    results = search(property='label', value='warrior')       # property == value

    # Search within a candidate list
    results = search('blue', candidates=room.contents)

    # Combine filters
    results = search('ring', isa=12, location=here)

    # All objects (no filter)
    results = search()

Architecture Notes
------------------
* :class:`SearchIndex` is attached to the ``Database`` instance as
  ``db._search_index`` and created on first use.
* The public API consists of two functions: :func:`search` (returns a list)
  and :func:`find` (returns the first match or ``None``).
* Both functions auto-inject the database when called from verb code
  (via ``builtins._database``); scripts must pass ``db=`` explicitly.

See Also
--------
* ``objects.py``  -- :class:`MOOObject`, :class:`ObjectFlags`.
* ``database.py`` -- :class:`Database` (hosts ``_mutation_gen``).
* ``builtins.py`` -- Verb-code namespace where ``search``/``find`` are
  injected.

Copyright (c) 2026
License: MIT
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import (
    TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Set, Union,
)

if TYPE_CHECKING:
    from .database import Database
    from .objects import MOOObject

from .objects import ObjectFlags

logger = logging.getLogger('megamoo.search')

# Sentinel for "value not provided" -- distinct from None so that
# search(property='foo', value=None) can match properties whose value IS None.
_SENTINEL = object()


# =============================================================================
# HELPERS
# =============================================================================

import re
# Regex that finds camelCase word boundaries:
#   - Between a lowercase letter and an uppercase letter:  "fooBar" -> "foo", "Bar"
#   - Between consecutive uppercase letters followed by lowercase: "XMLParser" -> "XML", "Parser"
_CAMEL_RE = re.compile(r'(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])')


def _tokenize(text: str) -> List[str]:
    """
    Break *text* into searchable word tokens.

    The tokeniser performs two passes:

    1. **Whitespace split** -- the lowercased text is split on whitespace,
       giving the "whole word" tokens.
    2. **CamelCase split** -- the *original-case* text is split on camelCase
       boundaries and any sub-words not already present are added.

    All tokens are lowercased.

    This dual approach means that ``"BlankRoom"`` produces
    ``['blankroom', 'blank', 'room']``, allowing a search for either
    ``"blank"`` or ``"room"`` to match.

    Args:
        text (str): Arbitrary display text (object name, noun, alias).

    Returns:
        List[str]: Lowercased tokens, including both whole words and
        camelCase sub-words.  May contain duplicates if the sub-words
        happen to match whole words.

    Examples::

        >>> _tokenize('BlankRoom')
        ['blankroom', 'blank', 'room']
        >>> _tokenize('a rusty sword')
        ['a', 'rusty', 'sword']
    """
    tokens: List[str] = []
    # Pass 1: whitespace-split, lowercased whole words
    for word in text.lower().split():
        tokens.append(word)
    # Pass 2: camelCase sub-words from original-case text
    for word in text.split():
        parts = _CAMEL_RE.split(word)
        if len(parts) > 1:
            for part in parts:
                low = part.lower()
                if low and low not in tokens:
                    tokens.append(low)
    return tokens


# =============================================================================
# FLAG NAME MAPPING
# =============================================================================

# Maps human-readable flag names (as used in search(flag='player')) to
# the corresponding ObjectFlags enum values.
_FLAG_MAP = {
    'player':     ObjectFlags.PLAYER,
    'programmer': ObjectFlags.PROGRAMMER,
    'wizard':     ObjectFlags.WIZARD,
    'fertile':    ObjectFlags.FERTILE,
    'readable':   ObjectFlags.READABLE,
    'writable':   ObjectFlags.WRITABLE,
}


# =============================================================================
# SEARCH INDEX -- Inverted Word Index with Generation Tracking
# =============================================================================

class SearchIndex:
    """
    Inverted word index over all objects in a :class:`~moo.database.Database`.

    The index is the performance backbone of the search system.  Rather than
    scanning every object for every query, it pre-computes three lookup
    tables at build time:

    * ``_word_index``  -- lowercased word token -> set of objnums.
      Populated from each object's ``noun``, ``name`` (display name) words,
      and ``aliases``.  Supports both word and prefix matching.
    * ``_noun_index``  -- lowercased full noun -> set of objnums.
      Used for exact-match queries against the object's ``noun`` field.
    * ``_alias_index`` -- lowercased full alias -> set of objnums.
      Used for exact-match queries against any of the object's aliases.

    **Staleness detection**: The index stores a generation counter
    (``_gen``) that mirrors ``db._mutation_gen`` at build time.  Before
    every query, :meth:`_ensure_fresh` compares the two counters and
    triggers a full :meth:`_rebuild` if they differ.

    **Ancestry cache**: :meth:`_ancestors_of` caches the full parent chain
    for each object (as a ``frozenset``) to accelerate ``isa`` filtering.
    The cache is cleared on every rebuild.

    Performance:
        A full rebuild of 10 000 objects takes approximately 10 ms.  Since
        rebuilds only happen after database mutations (not on every query),
        the amortised cost is negligible.

    Attributes:
        _db:           The :class:`~moo.database.Database` instance.
        _gen:          The ``_mutation_gen`` value at the time of the last
                       rebuild.  Initialised to ``-1`` to force the first build.
        _word_index:   ``Dict[str, Set[int]]`` -- word token -> objnums.
        _noun_index:   ``Dict[str, Set[int]]`` -- full noun -> objnums.
        _alias_index:  ``Dict[str, Set[int]]`` -- full alias -> objnums.
        _all_objnums:  ``Set[int]`` -- every valid objnum in the database.
        _parent_cache: ``Dict[int, frozenset]`` -- objnum -> ancestor objnums.
    """

    __slots__ = (
        '_db', '_gen',
        '_word_index', '_noun_index', '_alias_index',
        '_all_objnums', '_parent_cache',
    )

    def __init__(self, db: Database):
        """
        Create a new search index for the given database.

        The index starts empty (generation ``-1``), so the first call to
        any lookup method will trigger a full rebuild.

        Args:
            db (Database): The database to index.
        """
        self._db = db
        self._gen: int = -1  # force first rebuild
        self._word_index: Dict[str, Set[int]] = defaultdict(set)
        self._noun_index: Dict[str, Set[int]] = defaultdict(set)
        self._alias_index: Dict[str, Set[int]] = defaultdict(set)
        self._all_objnums: Set[int] = set()
        # parent_chain cache: objnum -> frozenset of all ancestor objnums
        self._parent_cache: Dict[int, frozenset] = {}

    # -------------------------------------------------------------------------
    # Rebuild logic
    # -------------------------------------------------------------------------

    def _ensure_fresh(self):
        """
        Check whether the index is current and rebuild if necessary.

        Compares ``self._gen`` to ``self._db._mutation_gen``.  If they
        differ, the database has been modified since the last build and
        a full :meth:`_rebuild` is triggered.  If they match, this is a
        no-op.
        """
        if self._gen == self._db._mutation_gen:
            return
        self._rebuild()

    def _rebuild(self):
        """
        Perform a full index rebuild from all objects in the database.

        Iterates every object via ``db.objects()`` and populates the three
        indexes (word, noun, alias) plus the ``_all_objnums`` set.  Also
        clears the parent-chain cache since object relationships may have
        changed.

        After the rebuild, ``self._gen`` is set to ``db._mutation_gen``
        so that subsequent :meth:`_ensure_fresh` calls are no-ops until
        the next mutation.
        """
        db = self._db
        word_idx: Dict[str, Set[int]] = defaultdict(set)
        noun_idx: Dict[str, Set[int]] = defaultdict(set)
        alias_idx: Dict[str, Set[int]] = defaultdict(set)
        all_objs: Set[int] = set()

        for obj in db.objects():
            n = obj.objnum
            all_objs.add(n)

            # Index the object's noun (primary identifier)
            noun = (obj.noun or '').strip()
            if noun:
                noun_low = noun.lower()
                noun_idx[noun_low].add(n)
                for word in _tokenize(noun):
                    word_idx[word].add(n)

            # Index the display name if it differs from the noun
            name = (obj.name or '').strip()
            if name and name.lower() != noun.lower():
                for word in _tokenize(name):
                    word_idx[word].add(n)

            # Index all aliases
            for alias in getattr(obj, 'aliases', []):
                alias_low = alias.lower().strip()
                if alias_low:
                    alias_idx[alias_low].add(n)
                    for word in _tokenize(alias):
                        word_idx[word].add(n)

        self._word_index = word_idx
        self._noun_index = noun_idx
        self._alias_index = alias_idx
        self._all_objnums = all_objs
        self._parent_cache.clear()  # invalidate ancestry cache
        self._gen = db._mutation_gen
        logger.debug(
            f"SearchIndex rebuilt: {len(all_objs)} objects, "
            f"{len(word_idx)} words, gen={self._gen}"
        )

    # -------------------------------------------------------------------------
    # Ancestry helper (cached)
    # -------------------------------------------------------------------------

    def _ancestors_of(self, objnum: int) -> frozenset:
        """
        Return all ancestor objnums of *objnum* (the full parent chain).

        Walks ``obj.parent`` links upward until reaching an invalid parent
        (``<= 0``) or a cycle.  Results are cached in ``_parent_cache`` for
        the lifetime of the current index generation.

        Args:
            objnum (int): The object number to find ancestors for.

        Returns:
            frozenset: Set of all ancestor objnums (does **not** include
            *objnum* itself).
        """
        if objnum in self._parent_cache:
            return self._parent_cache[objnum]

        ancestors = set()
        seen = set()       # cycle detection
        current = objnum
        db = self._db

        while True:
            try:
                obj = db.get_object(current)
            except KeyError:
                break
            p = obj.parent
            if p <= 0 or p in seen:
                break
            ancestors.add(p)
            seen.add(p)
            current = p

        result = frozenset(ancestors)
        self._parent_cache[objnum] = result
        return result

    def isa(self, objnum: int, ancestor: int) -> bool:
        """
        Test whether *objnum* is, or descends from, *ancestor*.

        This is the prototype-delegation equivalent of Evennia's typeclass
        ``isinstance`` check.  Returns ``True`` if *objnum* equals
        *ancestor* or if *ancestor* appears anywhere in *objnum*'s parent
        chain.

        Args:
            objnum (int):   The object to test.
            ancestor (int): The potential ancestor to look for.

        Returns:
            bool: ``True`` if *objnum* is (or inherits from) *ancestor*.
        """
        if objnum == ancestor:
            return True
        return ancestor in self._ancestors_of(objnum)

    # -------------------------------------------------------------------------
    # Query primitives
    # -------------------------------------------------------------------------

    def lookup_word(self, word: str) -> Set[int]:
        """
        Look up a single word token in the word index.

        Returns the set of objnums whose noun, name, or alias contained
        this word (as determined by :func:`_tokenize` at index time).

        Args:
            word (str): A single word token (case-insensitive).

        Returns:
            Set[int]: Matching objnums (may be empty).
        """
        self._ensure_fresh()
        return self._word_index.get(word.lower(), set())

    def lookup_noun(self, noun: str) -> Set[int]:
        """
        Look up an exact noun match (case-insensitive).

        Only matches the *full* noun string, not individual words within it.

        Args:
            noun (str): The noun to look up.

        Returns:
            Set[int]: Objnums whose ``noun`` field matches exactly.
        """
        self._ensure_fresh()
        return self._noun_index.get(noun.lower(), set())

    def lookup_alias(self, alias: str) -> Set[int]:
        """
        Look up an exact alias match (case-insensitive).

        Only matches complete alias strings, not partial words.

        Args:
            alias (str): The alias to look up.

        Returns:
            Set[int]: Objnums that have this exact alias.
        """
        self._ensure_fresh()
        return self._alias_index.get(alias.lower(), set())

    def lookup_prefix(self, prefix: str) -> Set[int]:
        """
        Find all objects whose indexed words start with *prefix*.

        Scans all keys in ``_word_index`` for the prefix.  This is O(N)
        in the number of unique indexed words, but the word count is
        typically small (a few thousand) so it remains fast.

        Args:
            prefix (str): The prefix to match (case-insensitive).

        Returns:
            Set[int]: Objnums with at least one indexed word starting with
            *prefix*.
        """
        self._ensure_fresh()
        prefix_low = prefix.lower()
        hits: Set[int] = set()
        for word, objnums in self._word_index.items():
            if word.startswith(prefix_low):
                hits.update(objnums)
        return hits

    def all_objnums(self) -> Set[int]:
        """
        Return the set of all valid object numbers in the database.

        Ensures the index is fresh before returning.

        Returns:
            Set[int]: Every objnum currently in the database.
        """
        self._ensure_fresh()
        return self._all_objnums


# =============================================================================
# search() -- The Main Public API
# =============================================================================

def search(
    query: Union[str, int, None] = None,
    *,
    exact: bool = False,
    isa: Union[int, MOOObject, None] = None,
    location: Union[int, MOOObject, None] = None,
    flag: Union[str, ObjectFlags, None] = None,
    property: Union[str, None] = None,
    value: Any = _SENTINEL,
    candidates: Union[Sequence[MOOObject], None] = None,
    db: Database = None,
) -> List[MOOObject]:
    """
    Search for objects in the database.

    This is the primary search entry point, callable from verb code as
    ``search(...)`` and from Python scripts with an explicit ``db=``
    parameter.  The search proceeds in three phases:

    **Phase 1 -- Query resolution**: The *query* parameter is resolved
    into an initial set of candidate object numbers:

    - ``int`` or ``"#N"`` string -- direct dbref lookup (O(1)).
    - ``str`` with ``exact=True`` -- matches against the noun index,
      alias index, and display names (case-insensitive).
    - ``str`` with ``exact=False`` (default) -- word-token and prefix
      matching via the inverted index.  Multi-word queries require *all*
      words to appear on the same object (intersection semantics).
    - ``None`` -- all objects are candidates.

    **Phase 2 -- Scope intersection**: If *candidates* was provided, the
    Phase 1 results are intersected with the candidate set to restrict
    the search to a known subset (e.g. a room's contents).

    **Phase 3 -- Filter application**: The remaining candidates are
    filtered by ``isa``, ``location``, ``flag``, and ``property``/``value``
    in that order.  Each filter is optional; only specified filters are
    applied.

    Args:
        query (str | int | None): A search string, object number (int), or
            dbref string (``"#N"``).  ``None`` returns all objects (subject
            to other filters).
        exact (bool): If ``True``, require an exact name/noun/alias match
            (case-insensitive).  If ``False`` (default), also match word
            fragments and prefixes.
        isa (int | MOOObject | None): Only return objects that descend from
            this parent (or are the parent itself).  Accepts an objnum or
            a :class:`MOOObject`.  Equivalent to Evennia's ``typeclass``
            filter.
        location (int | MOOObject | None): Only return objects at this
            location.  Accepts an objnum or a :class:`MOOObject`.
        flag (str | ObjectFlags | None): Only return objects with this flag
            set.  Accepts a string (``"player"``, ``"wizard"``,
            ``"programmer"``, ``"fertile"``, ``"readable"``, ``"writable"``)
            or an :class:`ObjectFlags` enum value.
        property (str | None): Only return objects that have this MOO
            property defined (local or inherited).
        value (Any): If *property* is specified, further filter to objects
            where the property's value equals this value.  If omitted (the
            default sentinel), only property *existence* is checked.
        candidates (Sequence[MOOObject] | None): If given, restrict the
            search to this list of objects instead of the full database.
            Useful for searching within a room's contents or a player's
            inventory.
        db (Database): The :class:`~moo.database.Database` instance.
            Normally auto-injected by the verb namespace; pass explicitly
            in standalone scripts.

    Returns:
        List[MOOObject]: Matching objects, sorted by objnum.  May be empty.

    Raises:
        ValueError: If *db* is ``None`` and no global database is available.

    Examples::

        search('sword')                             # word match
        search('Warrior', exact=True)               # exact noun/name
        search('#76')                               # dbref
        search(76)                                  # objnum
        search(isa=15)                              # all descendants of #15
        search(flag='player')                       # all players
        search('key', location=here)                # keys in this room
        search(property='label', value='warrior')   # class label match
        search('blue', candidates=room.contents)    # scoped search
    """
    # --- Resolve the database instance ---
    if db is None:
        from . import builtins as _b
        db = _b._database
    if db is None:
        raise ValueError("search() requires a database -- pass db= or call from verb code")

    # Get or create the SearchIndex (lazily attached to the database)
    idx: SearchIndex = getattr(db, '_search_index', None)
    if idx is None:
        idx = SearchIndex(db)
        db._search_index = idx
    idx._ensure_fresh()

    # ------------------------------------------------------------------
    # Phase 1: Resolve query -> initial candidate objnums
    # ------------------------------------------------------------------

    if candidates is not None:
        # Scoped search: start from the given candidate list
        candidate_nums = {obj.objnum for obj in candidates}
    else:
        candidate_nums = None  # means "all objects"

    hits: Optional[Set[int]] = None

    if query is not None:
        # --- Direct dbref lookup (int or "#N" string) ---
        if isinstance(query, int):
            hits = {query} if db.valid(query) else set()
        elif isinstance(query, str):
            q = query.strip()

            # "#N" dbref syntax
            if q.startswith('#') and q[1:].isdigit():
                objnum = int(q[1:])
                hits = {objnum} if db.valid(objnum) else set()

            elif exact:
                # --- Exact match: noun index + alias index + display name ---
                noun_hits = idx.lookup_noun(q)
                alias_hits = idx.lookup_alias(q)
                hits = noun_hits | alias_hits

                # Also scan display names (not separately indexed as exact)
                q_low = q.lower()
                for n in idx.all_objnums():
                    if candidate_nums is not None and n not in candidate_nums:
                        continue
                    try:
                        obj = db.get_object(n)
                        if obj.name.lower() == q_low:
                            hits.add(n)
                    except KeyError:
                        pass

            else:
                # --- Fuzzy match: word tokens + prefix matching ---
                words = q.lower().split()
                if len(words) == 1:
                    # Single word: union of exact word hit and prefix matches
                    word = words[0]
                    hits = idx.lookup_word(word) | idx.lookup_prefix(word)
                else:
                    # Multi-word: intersect per-word hits so that ALL words
                    # must appear somewhere on the same object
                    per_word = []
                    for word in words:
                        w_hits = idx.lookup_word(word) | idx.lookup_prefix(word)
                        per_word.append(w_hits)
                    if per_word:
                        hits = per_word[0]
                        for s in per_word[1:]:
                            hits = hits & s
                    else:
                        hits = set()
        else:
            hits = set()

    # ------------------------------------------------------------------
    # Phase 2: Intersect with candidate scope
    # ------------------------------------------------------------------

    if hits is not None and candidate_nums is not None:
        result_nums = hits & candidate_nums
    elif hits is not None:
        result_nums = hits
    elif candidate_nums is not None:
        result_nums = candidate_nums
    else:
        # No query and no candidates -> all objects in the database
        result_nums = set(idx.all_objnums())

    # ------------------------------------------------------------------
    # Phase 3: Apply filters (isa, location, flag, property)
    # ------------------------------------------------------------------

    # Resolve filter arguments to primitive types
    isa_num: Optional[int] = None
    if isa is not None:
        isa_num = isa.objnum if hasattr(isa, 'objnum') else int(isa)

    loc_num: Optional[int] = None
    if location is not None:
        loc_num = location.objnum if hasattr(location, 'objnum') else int(location)

    flag_enum: Optional[ObjectFlags] = None
    if flag is not None:
        if isinstance(flag, ObjectFlags):
            flag_enum = flag
        elif isinstance(flag, str):
            flag_enum = _FLAG_MAP.get(flag.lower())
            if flag_enum is None:
                logger.warning(f"search(): unknown flag name '{flag}'")
                return []

    has_filters = (isa_num is not None or loc_num is not None
                   or flag_enum is not None or property is not None)

    if not has_filters:
        # Fast path: no filters -- just resolve objnums to MOOObject instances
        results = []
        for n in sorted(result_nums):
            try:
                results.append(db.get_object(n))
            except KeyError:
                pass
        return results

    # Filtered path: test each candidate against all active filters
    results = []
    check_value = (value is not _SENTINEL)

    for n in sorted(result_nums):
        try:
            obj = db.get_object(n)
        except KeyError:
            continue

        # isa filter: object must descend from (or be) isa_num
        if isa_num is not None and not idx.isa(n, isa_num):
            continue

        # location filter: object must be at the specified location
        if loc_num is not None and obj._location_id != loc_num:
            continue

        # flag filter: object must have the specified flag set
        if flag_enum is not None and not obj.has_flag(flag_enum):
            continue

        # property filter: object must have the property (and optionally
        # its value must match)
        if property is not None:
            if not obj.has_property(property, database=db):
                continue
            if check_value:
                try:
                    prop = obj.get_property(property, db)
                except (KeyError, AttributeError):
                    continue
                if prop != value:
                    continue

        results.append(obj)

    return results


# =============================================================================
# find() -- Single-Object Convenience Wrapper
# =============================================================================

def find(
    query: Union[str, int, None] = None,
    *,
    db: Database = None,
    **kwargs,
) -> Optional[MOOObject]:
    """
    Find a single object, or ``None`` if not found.

    A thin convenience wrapper around :func:`search` that returns the first
    match directly instead of a list.  Accepts all the same keyword
    arguments (``exact``, ``isa``, ``location``, ``flag``, ``property``,
    ``value``, ``candidates``).

    This is the recommended function when you expect exactly one result
    (e.g. looking up a specific dbref or a uniquely-named object).

    Args:
        query (str | int | None): Search string, objnum (``int``), or dbref
            string (``"#N"``).
        db (Database): Database instance (auto-injected in verb code).
        **kwargs: Any additional filters accepted by :func:`search`.

    Returns:
        MOOObject or ``None``: The first matching object, or ``None`` if no
        objects matched the query and filters.

    Examples::

        obj = find(1065)
        obj = find('#1065')
        obj = find('Warrior', exact=True)
        obj = find('key', location=here)
    """
    results = search(query, db=db, **kwargs)
    return results[0] if results else None
