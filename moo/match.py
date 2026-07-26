"""
MegaMOO Object Matching

This module implements object matching and name resolution, allowing players
to refer to objects by name, number, or various shorthand notations.

Matching follows MOO conventions:
    - Exact names match first
    - Aliases are checked
    - Articles (a, an, the) are ignored
    - Case-insensitive matching
    - Multiple match scopes (inventory, room, global)

Copyright (c) 2026
License: MIT
"""

from typing import List, Optional, Set, Tuple
from enum import Enum
import re
import logging

from .objects import MOOObject
from .utils import parse_object_ref

logger = logging.getLogger('megamoo.match')


class MatchScope(Enum):
    """
    Scope for object matching.
    
    Determines where to search for matching objects.
    """
    ME = 'me'              # Player's inventory
    HERE = 'here'          # Current location contents
    LOCATION = 'location'  # The location object itself
    EXITS = 'exits'        # Exits from current location
    GLOBAL = 'global'      # Global objects (those with #player.location = #-1)
    ABSOLUTE = 'absolute'  # Any object by number
    ALL = 'all'           # All of the above


class MatchError(Exception):
    """Raised when object matching fails or is ambiguous."""
    pass


class ObjectMatcher:
    """
    Matches object names to actual objects.
    
    This class handles the complex logic of finding objects based on
    player input, considering scope, permissions, and ambiguity.
    
    Attributes:
        database: Database instance for object lookup
        player: Player object doing the matching
        scope: Where to search for objects
    """
    
    def __init__(self, database, player: MOOObject, scope: MatchScope = MatchScope.ALL):
        """
        Initialize matcher.
        
        Args:
            database: Database instance
            player: Player object
            scope: Search scope
        """
        self.database = database
        self.player = player
        self.scope = scope
        
    def match(self, name: str) -> MOOObject:
        """
        Match a name to an object.

        Supports ordinals (``2nd sword``, ``3 ball``), adjectives
        (``big blue sword``), articles (``the sword``), keywords
        (``me``, ``here``), and object references (``#123``).

        Args:
            name: Object name, alias, or #number

        Returns:
            MOOObject: Matched object

        Raises:
            MatchError: If no match or ambiguous match

        Examples:
            matcher.match("lamp")        # Match by name
            matcher.match("#123")        # Match by number
            matcher.match("the sword")   # Ignore article
            matcher.match("2nd sword")   # Ordinal support
        """
        from .match_utils import match as mu_match, omatch

        # Try keywords and object references (me, here, #N, $name)
        obj = omatch(name, self.player, self.database)
        if obj is not None:
            return obj

        # Remove articles for #N check
        name_clean = self._remove_articles(name)

        # Try to match by object number
        objnum = parse_object_ref(name_clean)
        if objnum is not None:
            if self.scope == MatchScope.ABSOLUTE or self._is_visible(objnum):
                from .search import find
                obj = find(objnum, db=self.database)
                if obj is not None:
                    return obj
                raise MatchError(f"Object #{objnum} not found")

        # Get candidate objects based on scope
        candidates = self._get_candidates()

        # Delegate to match_utils.match() which handles ordinals,
        # adjectives, and prefix matching
        result = mu_match(name, candidates)
        if result is not None:
            return result

        raise MatchError(f"I don't see '{name}' here.")
        
    def match_multiple(self, name: str) -> List[MOOObject]:
        """
        Match a name that could refer to multiple objects.
        
        Args:
            name: Object name or pattern
            
        Returns:
            List[MOOObject]: All matching objects
            
        Examples:
            matcher.match_multiple("all coins")
            matcher.match_multiple("*")
        """
        # Handle special patterns
        if name == "*" or name.lower() == "all":
            return self._get_candidates()
            
        # Handle "all <name>" pattern
        if name.lower().startswith("all "):
            name = name[4:]
            
        name_clean = self._remove_articles(name)
        candidates = self._get_candidates()
        
        # Match all candidates that fit
        matches = [obj for obj in candidates if self._name_matches(obj, name_clean, exact=False)]
        
        return matches
        
    def _get_candidates(self) -> List[MOOObject]:
        """
        Get list of candidate objects based on scope.
        
        Returns:
            List of objects to search
        """
        candidates = []
        
        try:
            if self.scope in (MatchScope.ME, MatchScope.ALL):
                # Player's inventory
                candidates.extend(self.player.contents)
                        
            if self.scope in (MatchScope.HERE, MatchScope.ALL):
                # Current location's contents
                location = self.player.location
                if location:
                    for obj in location.contents:
                        if obj.objnum != self.player.objnum:  # Don't include self
                            candidates.append(obj)
                                
            if self.scope in (MatchScope.LOCATION, MatchScope.ALL):
                # The location itself
                location = self.player.location
                if location:
                    candidates.append(location)
                        
            if self.scope in (MatchScope.EXITS, MatchScope.ALL):
                # Exits (objects with special 'exit' property or flag)
                location = self.player.location
                if location:
                    for obj in location.contents:
                        if self._is_exit(obj):
                            candidates.append(obj)
                            
        except Exception as e:
            logger.error(f"Error getting candidates: {e}")

        # Deduplicate candidates while preserving order
        seen = set()
        unique_candidates = []
        for obj in candidates:
            if obj.objnum not in seen:
                seen.add(obj.objnum)
                unique_candidates.append(obj)
        return unique_candidates
        
    def _name_matches(self, obj: MOOObject, name: str, exact: bool = False) -> bool:
        """
        Check if an object name matches the search string.
        
        Args:
            obj: Object to check
            name: Name to match
            exact: Whether to require exact match
            
        Returns:
            bool: True if name matches
        """
        if not obj.name:
            return False

        name_lower = name.lower()

        # Check object name
        if exact:
            if obj.name.lower() == name_lower:
                return True
        else:
            if name_lower in obj.name.lower():
                return True
                
        # Check aliases
        for alias in obj.aliases:
            if exact:
                if alias.lower() == name_lower:
                    return True
            else:
                if name_lower in alias.lower():
                    return True
                    
        return False
        
    def _remove_articles(self, name: str) -> str:
        """
        Remove articles from object name.
        
        Args:
            name: Original name
            
        Returns:
            str: Name without leading articles
        """
        # Remove leading articles
        articles = ['a ', 'an ', 'the ', 'some ']
        name_lower = name.lower()
        
        for article in articles:
            if name_lower.startswith(article):
                return name[len(article):]
                
        return name
        
    def _is_visible(self, objnum: int) -> bool:
        """
        Check if an object is visible to the player.
        
        Args:
            objnum: Object number
            
        Returns:
            bool: True if player can see the object
        """
        try:
            obj = self.database.get_object(objnum)
            
            # Wizards can see everything
            if self.player.is_wizard:
                return True
                
            # Check if object is in a visible location
            # This is simplified - real MOO has complex visibility rules
            if obj._location_id == self.player.objnum:
                return True
            if obj._location_id == self.player._location_id:
                return True
            if obj.objnum == self.player._location_id:
                return True
                
            return False
        except Exception:
            return False

    def _is_exit(self, obj: MOOObject) -> bool:
        """
        Check if an object is an exit.
        
        Args:
            obj: Object to check
            
        Returns:
            bool: True if object is an exit
        """
        # Check for 'destination' property (common exit pattern)
        try:
            dest = obj.get_property('destination', self.database)
            return dest is not None and dest > 0
        except Exception:
            pass
            
        # Check for 'exit' in name or aliases
        name_lower = obj.name.lower()
        if 'exit' in name_lower or 'door' in name_lower:
            return True
            
        return False
        
    def _disambiguate(self, matches: List[MOOObject], name: str) -> Optional[MOOObject]:
        """
        Try to pick the best match from multiple matches.
        
        Args:
            matches: List of matching objects
            name: Original search name
            
        Returns:
            MOOObject or None: Best match, or None if still ambiguous
        """
        # Prefer objects in inventory over those in room
        inventory_matches = [obj for obj in matches if obj._location_id == self.player.objnum]
        if len(inventory_matches) == 1:
            return inventory_matches[0]
            
        # Prefer exact name matches over partial
        exact_matches = [obj for obj in matches if obj.name.lower() == name.lower()]
        if len(exact_matches) == 1:
            return exact_matches[0]
            
        # Can't disambiguate
        return None


def find_by_name(database, name: str, parent: Optional[int] = None) -> List[MOOObject]:
    """
    Find all objects with a given name.
    
    This is a global search, not scoped to a player.
    Delegates to :func:`~moo.search.search` for indexed lookup.
    
    Args:
        database: Database instance
        name: Object name to search for
        parent: If provided, only search descendants of this parent
        
    Returns:
        List of matching objects
    """
    from .search import search
    return search(name, exact=True, isa=parent, db=database)


def match_preposition(prep: str) -> Optional[str]:
    """
    Match a preposition to its canonical form.

    Aliases in PREPOSITIONS can be plain strings (exact match) or
    tuples ``(word, min_chars)`` for prefix matching down to
    *min_chars* characters.

    Args:
        prep: Preposition to match

    Returns:
        str: Canonical preposition, or None if not recognized

    Examples:
        >>> match_preposition("on")
        'on'
        >>> match_preposition("on top of")
        'on'
        >>> match_preposition("into")
        'in'
        >>> match_preposition("beh")
        'behind'
        >>> match_preposition("=")
        '='
    """
    from .globals import PREPOSITIONS

    prep_lower = prep.lower()

    for canonical, aliases in PREPOSITIONS.items():
        for alias in aliases:
            if isinstance(alias, tuple):
                word, min_chars = alias
                word_lower = word.lower()
                # Exact match
                if prep_lower == word_lower:
                    return canonical
                # Prefix match: query must be at least min_chars and be
                # a prefix of the full word
                if (len(prep_lower) >= min_chars
                        and word_lower.startswith(prep_lower)):
                    return canonical
            else:
                if prep_lower == alias.lower():
                    return canonical

    return None
