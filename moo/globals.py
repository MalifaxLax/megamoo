"""
MegaMOO Server Settings and Global Constants
(`moo/globals.py`)

This module is the single source of truth for all server-wide configuration
constants, preposition tables, direction maps, type registries, and default
values used throughout the MegaMOO engine.

Key Responsibilities:
    - Define the **preposition tables** consumed by the command parser
      (``split_on_prep``, ``prep_match``, etc.) when decomposing player
      input into verb / direct-object / preposition / indirect-object.
    - Provide **direction constants** (``DNAMES``, ``FDNAMES``, ``RFDNAMES``,
      ``RETEXIT``, etc.) used by exit objects, room builders, and the
      ``@dig`` command to represent the 12-direction compass.
    - Publish **type registries** (``ROOM_TYPES``, ``EXIT_TYPES``,
      ``TCLASSES``) that map user-friendly type names to their parent
      prototype object numbers in the database.
    - Store **server defaults** for networking, security, logging, and
      performance tuning, giving operators a clear set of knobs to tweak.

Architecture Notes:
    This module is imported by virtually every other module in the
    ``moo`` package.  Because it contains only constants and a few
    trivial helper functions it has **no imports of other moo modules**
    (except ``re`` from the standard library), which avoids circular
    import chains.

    Values here are compile-time defaults.  Runtime overrides can be
    supplied via the server configuration file (``megamoo.yml``) and are
    managed by ``moo.config``.

Typical Usage::

    from moo.globals import DIRECTIONS, DNAMES, LOGIN_ROOM
    from moo.globals import PREPOSITIONS, ALL_PREPOSITIONS
    from moo.globals import ROOM_TYPES, EXIT_TYPES, TCLASSES

Copyright (c) 2026
License: MIT
"""

# ============================================================================
# PREPOSITION DEFINITIONS
# ============================================================================
#
# The preposition system is central to command parsing in a MOO.  When a
# player types something like:
#
#     put sword in chest
#
# the parser must split the input into:
#     verb = "put"
#     direct object = "sword"
#     preposition = "in"
#     indirect object = "chest"
#
# ``PREPOSITIONS`` maps each **canonical** preposition to a list of surface
# forms (aliases) the player might actually type.  The canonical form is
# what gets stored in ``prepstr`` inside the verb namespace.

# Preposition mapping: canonical form -> list of aliases
# The parser uses this to match prepositions in commands
PREPOSITIONS = {
    # Aliases can be plain strings (exact match only) or tuples
    # (word, min_chars) for prefix matching.  A tuple like ('behind', 3)
    # means 'beh', 'behi', 'behin', and 'behind' all match.
    'in':      ['in', ('inside', 3), ('into', 3)],
    'on':      ['on', ('onto', 3), ('upon', 3), 'on top of', ('atop', 3)],
    'from':    [('from', 3), 'out of'],
    'with':    [('with', 3), ('using', 3)],
    'at':      ['at', 'to'],
    'as':      ['as'],
    'for':     ['for'],
    'about':   [('about', 4), ('concerning', 3)],
    'through': [('through', 5), 'thru'],
    'under':   [('under', 3), ('underneath', 5), ('beneath', 3)],
    'behind':  [('behind', 3)],
    'over':    [('over', 3), ('above', 4)],
    'across':  [('across', 3)],
    'off':     ['off'],
    'between': [('between', 3)],
    'among':   [('among', 3), ('amongst', 3)],
    '=': ['='],  # Assignment preposition (e.g., @name obj=value)
    '?': ['?'],  # Query preposition (e.g., @property obj?prop)
}

# Compound prepositions — tuples specify min_chars for the last word.
# Plain strings are exact match only.
COMPOUND_PREPS = [
    'from off',
    ('from under', 3),
    ('from behind', 3),
    ('from beneath', 3),
    ('from atop', 3),
]

# Flat list of all recognized prepositions (for quick lookup).
# Built once at import time by flattening the PREPOSITIONS dict.
ALL_PREPOSITIONS = []
for _canonical, _aliases in PREPOSITIONS.items():
    for _a in _aliases:
        ALL_PREPOSITIONS.append(_a[0] if isinstance(_a, tuple) else _a)

# Special prepositions that can be used without surrounding whitespace.
# The parser handles these specially to allow compact syntax like:
#   @name #10=value    (no spaces around =)
#   @name #10 = value  (with spaces)
#   @name #10= value   (space after only)
#   @name #10 =value   (space before only)
SPECIAL_PREPOSITIONS = ['=', '?', ':']

# ============================================================================
# PREPOSITION REGEX PATTERNS
# ============================================================================
#
# These compiled regex patterns are used by ``moo.match_utils.split_on_prep``
# and ``moo.match_utils.prep_match`` to locate the preposition boundary
# in a command string.  The pattern supports partial spellings where
# specified by the (alias, min_chars) tuples in PREPOSITIONS.
#
# Generated dynamically from PREPOSITIONS and COMPOUND_PREPS.

import re

def _alias_prefixes(word, min_chars):
    """Generate all prefixes of *word* from *min_chars* to full length
    (longest first)."""
    return [word[:i] for i in range(len(word), min_chars - 1, -1)]

def _build_prep_regex_pattern():
    """Build PREP_REGEX_PATTERN from PREPOSITIONS dict and COMPOUND_PREPS."""
    seen = set()
    alts = []

    def _add(variant):
        low = variant.lower()
        if low not in seen:
            seen.add(low)
            alts.append(low)

    # Single-word preps with per-alias prefix expansion
    for canonical, aliases in PREPOSITIONS.items():
        if canonical in ('=', '?', ':'):
            continue
        for alias in aliases:
            if isinstance(alias, tuple):
                word, min_chars = alias
                if ' ' not in word:
                    for prefix in _alias_prefixes(word, min_chars):
                        _add(prefix)
                else:
                    _add(word)  # multi-word tuple alias — exact only
            else:
                if ' ' not in alias:
                    _add(alias)  # plain string — exact only

    # Compound preps — expand prefixes on the last word
    for entry in COMPOUND_PREPS:
        if isinstance(entry, tuple):
            phrase, min_chars = entry
            words = phrase.split()
            head = ' '.join(words[:-1])
            for prefix in _alias_prefixes(words[-1], min_chars):
                _add(f"{head} {prefix}")
        else:
            _add(entry)

    # Sort longest first so regex matches the most specific form
    alts.sort(key=lambda x: -len(x))

    joined = '|'.join(alts)
    return rf'((^|\s)({joined})(\s)|=|:|\?)'

PREP_REGEX_PATTERN = _build_prep_regex_pattern()
PREP_REGEX = re.compile(PREP_REGEX_PATTERN, re.I)

# Special preposition regex (for =, :, ?)
# These can appear without spaces: obj=value, obj:verb, obj?prop
SPECIAL_PREP_REGEX = re.compile(r'[=:?]')

# Non-space preposition regex (just the special ones that never require
# surrounding whitespace).  Used by the parser to split builder-style
# commands like ``@name #10=My Sword``.
NSPPREPS_REGEX = re.compile(r'[=:]')

# ============================================================================
# COMMAND PARSING SETTINGS
# ============================================================================
#
# Limits and defaults that govern how the command-parsing pipeline
# (``moo.parser``) handles player input.

# Maximum command length (characters) -- lines longer than this are
# silently truncated to prevent memory abuse.
MAX_COMMAND_LENGTH = 8192

# Maximum argument length (characters) -- the "args" portion of a
# parsed command is capped at this length.
MAX_ARGUMENT_LENGTH = 4096

# Command history size (per player) -- how many past commands the
# server remembers for each connection (used by the ``!`` recall prefix).
COMMAND_HISTORY_SIZE = 100

# Timeout for command execution (seconds) -- a verb call that exceeds
# this wall-clock limit is killed to prevent infinite loops.
COMMAND_TIMEOUT = 30

# How many verb threads exist.  Verbs are serialised by the baton in
# verb_baton -- only one ever executes -- so this is not a concurrency
# setting.  It bounds how many verbs may sit *suspended* at once, each
# holding a parked thread so it can resume mid-execution.  Past this,
# new commands wait for a free worker rather than being refused.
VERB_POOL_SIZE = 32

# ============================================================================
# OBJECT SYSTEM SETTINGS
# ============================================================================
#
# Fundamental numeric constants governing the object database.

# Object room - properties on this object map names to object numbers.
# The ``@make`` command consults #8 to translate a template name into
# a parent objnum, e.g. ``@make sword`` reads ``#8.sword`` to get the
# parent prototype objnum for swords.
OBJECT_ROOM = 8

# Starting object number for user-created objects.  Objects 0-4 are
# reserved for core system objects (System, RootClass, PlayerObjectDB,
# etc.).
FIRST_USER_OBJECT = 5

# Maximum number of objects in database -- a safety ceiling.
MAX_OBJECTS = 1000000

# Maximum property name length
MAX_PROPERTY_NAME_LENGTH = 64

# Maximum verb name length
MAX_VERB_NAME_LENGTH = 64

# Maximum number of verbs per object
MAX_VERBS_PER_OBJECT = 1000

# Maximum number of properties per object
MAX_PROPERTIES_PER_OBJECT = 1000

# ============================================================================
# DATABASE SETTINGS
# ============================================================================
#
# Configuration for the disk-backed object database (``moo.database``).

# Checkpoint interval (seconds) -- how often the server creates a full
# compressed snapshot of the database.
DEFAULT_CHECKPOINT_INTERVAL = 300  # 5 min

# Auto-save interval (seconds) -- how often dirty objects are flushed
# to disk.  This is separate from checkpointing; auto-save writes
# individual JSON files, not a tarball.
DEFAULT_AUTOSAVE_INTERVAL = 300  # 5 minutes

# Maximum transaction log size before rotation (bytes)
MAX_TRANSACTION_LOG_SIZE = 10 * 1024 * 1024  # 10 MB

# Number of checkpoint backups to keep
MAX_CHECKPOINT_BACKUPS = 10

# ============================================================================
# NETWORK SETTINGS
# ============================================================================
#
# Defaults for the Telnet / WebSocket listener (``moo.network``).

# Default server port
DEFAULT_PORT = 6770

# Default server host -- 0.0.0.0 means listen on all interfaces.
DEFAULT_HOST = '0.0.0.0'

# Maximum number of simultaneous connections
DEFAULT_MAX_CONNECTIONS = 500

# Connection timeout (seconds) -- idle connections are closed after
# this duration with no input.
CONNECTION_TIMEOUT = 300  # 5 minutes

# Default text wrap width (columns).  Text wider than this is
# soft-wrapped before being sent to the client.  Set to 0 to
# disable server-side wrapping (let the client handle it).
WRAP_WIDTH = 121

# Input buffer size (bytes)
INPUT_BUFFER_SIZE = 8192

# Output buffer size (bytes)
OUTPUT_BUFFER_SIZE = 8192

# Maximum login attempts before disconnect
MAX_LOGIN_ATTEMPTS = 3

# ============================================================================
# PROTOCOL SETTINGS
# ============================================================================
#
# Feature flags for optional MUD client protocols.  When enabled,
# the server will negotiate these extensions during the Telnet
# handshake (or over WebSocket sub-protocols).

# MXP (MUD Extension Protocol) -- enables clickable links and inline
# images in supporting clients.
ENABLE_MXP = True

# GMCP (Generic MUD Communication Protocol) -- sends structured JSON
# data (room info, character stats, etc.) out-of-band.
ENABLE_GMCP = True

# MSDP (Mud Server Data Protocol) -- older structured data protocol.
ENABLE_MSDP = True

# MSSP (Mud Server Status Protocol) -- allows MUD listing sites to
# query server metadata (name, player count, etc.).
ENABLE_MSSP = True

# ANSI color support -- when True, color codes (|r, |g, etc.) in
# messages are translated to ANSI escape sequences.
ENABLE_ANSI_COLOR = True

# UTF-8 encoding -- when True, the server negotiates UTF-8 with
# the client.  When False, ASCII-only.
ENABLE_UTF8 = True

# ============================================================================
# PERFORMANCE SETTINGS
# ============================================================================
#
# Tuning knobs that control resource usage and protect against
# runaway verb code.

# Task tick limit (execution budget per verb).  Each Python bytecode
# instruction counts as one tick.  Verbs that exceed this limit are
# forcibly terminated.
DEFAULT_TICK_LIMIT = 100000

# Maximum recursion depth for verb calls -- call_verb() refuses to
# recurse deeper than this to prevent infinite verb-call chains.
MAX_VERB_RECURSION = 50

# Object cache size (number of objects to keep in memory).  The
# database evicts the least-recently-used objects when the cache is
# full and loads them back from disk on next access.
OBJECT_CACHE_SIZE = 1000

# Property cache size -- number of resolved (inherited) property
# values to cache per object.
PROPERTY_CACHE_SIZE = 10000

# ============================================================================
# SECURITY SETTINGS
# ============================================================================
#
# Authentication and authorization defaults.

# Require passwords for player accounts.  Set to True for any
# server exposed to the internet.
REQUIRE_PASSWORDS = False  # Set to True for production

# Minimum password length
MIN_PASSWORD_LENGTH = 6

# Maximum password length
MAX_PASSWORD_LENGTH = 128

# Password hashing algorithm
PASSWORD_HASH_ALGORITHM = 'sha256'

# Enable wizard commands only for wizards
ENFORCE_WIZARD_PERMISSIONS = True

# ============================================================================
# LOGGING SETTINGS
# ============================================================================

# Default log level
DEFAULT_LOG_LEVEL = 'INFO'

# Log file path
DEFAULT_LOG_FILE = 'megamoo.log'

# Maximum log file size before rotation (bytes)
MAX_LOG_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

# Number of log file backups to keep
MAX_LOG_BACKUPS = 5

# ============================================================================
# DEVELOPER SETTINGS
# ============================================================================

# Verb auto-reload watcher -- polls the on-disk verb tree
# (``<moo_verb_path>/<objnum>/*.py``) and hot-loads changed files into
# the live database.  Convenient for development; set False in
# production so verb code only changes through in-game tools.
DEFAULT_AUTORELOAD_VERBS = True

# Seconds between polls of the verb tree when auto-reload is enabled.
DEFAULT_AUTORELOAD_INTERVAL = 2.0

# ============================================================================
# SERVER INFORMATION
# ============================================================================

# Room where new players are placed on creation.  This is the OOC
# staging area -- when a player puppets an IC character, that
# character is moved to its stored ``last_location``.
LOGIN_ROOM = 14

# Server name
DEFAULT_SERVER_NAME = 'MegaMOO Server'

# Server version (imported from __init__.py)
SERVER_VERSION = '0.10.0-beta13'

# Server description
SERVER_DESCRIPTION = 'A Python implementation of LambdaMOO'

# Administrator contact
DEFAULT_ADMIN_EMAIL = ''

# Server website
DEFAULT_SERVER_WEBSITE = ''

# ============================================================================
# MESSAGE TEMPLATES
# ============================================================================
#
# Default messages shown to players at various connection lifecycle
# points.  These can be overridden by properties on system objects
# (e.g. ``#1.welcome_message``).

# Welcome message for new connections
DEFAULT_WELCOME_MESSAGE = """
MegaMOO Server
============

Please enter your character name (or 'new' to create a character):
"""

# Message of the day
DEFAULT_MOTD = """
Welcome to MegaMOO!

Type 'help' for help, or 'quit' to disconnect.
"""

# Game entry message (shown when puppeting into an IC character)
GAME_ENTRY_MESSAGE = "You descend into virtuality..."

# Shutdown message
DEFAULT_SHUTDOWN_MESSAGE = "Server shutting down for maintenance."

# Connection limit message
CONNECTION_LIMIT_MESSAGE = "Server is full. Please try again later."

# ============================================================================
# GENDER / PRONOUN SETTINGS
# ============================================================================
#
# Pronoun tables for the emit-substitution system (``moo.string_utils``).
# When a message contains tokens like ``%ps`` (pronoun-subject) or
# ``%po`` (pronoun-object), the string-utils module looks up the
# character's ``gender`` property in this map and substitutes the
# appropriate pronoun.
#
# Keys:
#   ps = pronoun subject   ("he", "she", "they", "it")
#   po = pronoun object    ("him", "her", "them", "it")
#   pp = pronoun possessive ("his", "her", "their", "its")
#   pa = pronoun absolute  ("his", "hers", "theirs", "its")
#   pr = pronoun reflexive ("himself", "herself", "themself", "itself")

GENDER_PRONOUN_MAP = {
    "male":      {"ps": "he",   "po": "him",  "pp": "his",   "pa": "his",    "pr": "himself"},
    "female":    {"ps": "she",  "po": "her",  "pp": "her",   "pa": "hers",   "pr": "herself"},
    "neutral":   {"ps": "it",   "po": "it",   "pp": "its",   "pa": "its",    "pr": "itself"},
    "ambiguous": {"ps": "they", "po": "them", "pp": "their", "pa": "theirs", "pr": "themself"},
}

# ============================================================================
# SUBSTITUTION SIGILS
# ============================================================================

#: Prefix characters that introduce a substitution or colour token.  The
#: **first** is canonical -- what new code should write, and what the
#: migration tool converts to.  The rest stay recognised so that worlds
#: written before the change keep working untouched.
#:
#: Why `&` and not `%`: `%` is Python's string-formatting operator, so
#: `"%<245>%s" % name` raises `ValueError: unsupported format character
#: '<'`.  The most common formatting idiom in the language collides with
#: the most common display idiom in the engine, and the failure is a
#: run-time error in whichever branch happens to build that string.
#:
#: `&` was chosen over `|` by counting real game text: across 5,217
#: literal output strings, `%` appeared 1,132 times, `|` 14, and `&` zero.
#: `|` is also common in table borders and ASCII art -- the startup banner
#: alone uses it 186 times.  `&` is the Diku/Merc convention besides, so
#: MUD authors arrive already knowing it.
#:
#: Set this to '&' alone once every verb file and stored string in a
#: database has been converted (tools/migrate_sigil.py).  That is what
#: finally makes a literal per-cent sign safe in game text; while `%`
#: stays here, raw output still has to escape it.
SUBST_SIGILS = '&'

#: The canonical sigil -- what to emit when generating tokens.
SIGIL = SUBST_SIGILS[0]

#: A regex character class matching any recognised sigil.
SIGIL_CLASS = '[' + re.escape(SUBST_SIGILS) + ']'

# Matches &ps, &po, &pp, &pa, &pr (and legacy %ps, $ps, ...)
RE_GENDER_PRONOUN = re.compile(SIGIL_CLASS + r"[pP][sSoOpPaArR]")

# ============================================================================
# DIRECTION CONSTANTS
# ============================================================================
#
# The 12-direction compass used by the room/exit system.  Indices 0-11
# are used as positional identifiers throughout the exit code:
#
#   Index:  0      1      2     3     4    5    6    7   8  9  10  11
#   Dir:    north  south  east  west  ne   nw   se   sw  u  d  o   in
#
# ``DNAMES``   -- canonical short direction names (used as property keys)
# ``FDNAMES``  -- full display names (used in exit messages)
# ``RFDNAMES`` -- reverse full display names (opposite directions)
# ``DALIASES`` -- [full, short] pairs for matching player input
# ``RETEXIT``  -- maps a direction to its opposite for return-exit creation

# All recognized direction inputs (short + full names).
# Used by the parser to detect when a bare word like "north" or "n"
# should be treated as a direction command rather than an object match.
DIRECTIONS = [
    'n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw', 'u', 'd', 'o', 'in',
    'north', 'south', 'east', 'west', 'northeast', 'northwest',
    'southeast', 'southwest', 'up', 'down', 'out',
]

# Canonical short direction names (index 0-11)
DNAMES = ['north', 'south', 'east', 'west', 'ne', 'nw', 'se', 'sw', 'u', 'd', 'o', 'in']

# Full direction names (for exit messages)
FDNAMES = ['north', 'south', 'east', 'west', 'northeast', 'northwest',
           'southeast', 'southwest', 'up', 'down', 'out', 'in']

# Reverse full direction names (opposite directions).
# ``RFDNAMES[i]`` is the opposite of ``FDNAMES[i]``.
RFDNAMES = ['south', 'north', 'west', 'east', 'southwest', 'southeast',
            'northwest', 'northeast', 'down', 'up', 'in', 'out']

# Aliases per direction index (full name + short name).
# Used by ``match_utils`` when resolving a player's direction input
# to a direction index.
DALIASES = [
    ['north', 'n'], ['south', 's'], ['east', 'e'], ['west', 'w'],
    ['northeast', 'ne'], ['northwest', 'nw'], ['southeast', 'se'],
    ['southwest', 'sw'], ['up', 'u'], ['down', 'd'], ['out', 'o'],
]

# Reverse exit mapping: direction -> its opposite.
# Used by ``@dig`` when creating return exits automatically.
RETEXIT = {
    'north': 'south', 'south': 'north',
    'east': 'west', 'west': 'east',
    'ne': 'sw', 'nw': 'se', 'se': 'nw', 'sw': 'ne',
    'u': 'd', 'd': 'u',
}

# ============================================================================
# EXIT MESSAGE TEMPLATES
# ============================================================================
#
# Default templates for directional exit success/failure/drop messages.
# These are assigned to newly-created exits and can be overridden per
# exit object.
#
# Substitution tokens:
#   %MODE   -- first-person movement verb (e.g. "walk", "fly")
#   %OMODE  -- third-person movement verb (e.g. "walks", "flies")
#   %S      -- the player's styled display name
#   %1      -- the direction name
#   %dir    -- synonym for %1

# Default directional exit messages
# %MODE/%OMODE are substituted at move time with movement mode verbs
# %S is the player's display name, %1 is the direction name
ESUCC = "You &MODE &1."
EOSUCC = "&S &OMODE &1."
EODROP = "&S &OMODE in from the &1."

# Default directional exit failure messages
DIRECTIONAL_EXIT_FAILURES = {
    'succ': "You &MODE &dir.",
    'osucc': "&S &OMODE &dir.",
    'drop': '',
    'odrop': "&S &OMODE in from the &dir.",
}

# Success message property aliases (short -> canonical mapping).
# Used by ``@success``, ``@osuccess``, ``@drop``, etc. to resolve
# abbreviated property names to their canonical slot names.
SUCCALIASES = ['succ', 'osuc', 'drop', 'odro', 'fail', 'ofai', 'lock', 'oloc']
SUCCNAMES = ['success', 'osuccess', 'drop', 'odrop', 'failure', 'ofailure', 'lockfail', 'olockfail']

# Success property index lookup (name/abbreviation -> slot index).
# Multiple abbreviations may map to the same slot.
SUCCESS_INDEX = {
    'success': 0, 'succ': 0, 'succe': 0,
    'osuccess': 1, 'osucc': 1, 'osucce': 1, 'osucces': 1,
    'drop': 2,
    'odrop': 3,
    'lock': 4,
    'olock': 5,
}

# ============================================================================
# ROOM TYPES (objnum mappings)
# ============================================================================
#
# Maps user-friendly room type names to the objnum of the prototype
# parent object.  Used by ``@dig`` and ``@make`` when creating new rooms.

ROOM_TYPES = {
    'room': 15, 'baseroom': 15, 'base': 15,
    'ooc': 16, 'oocroom': 16, 'oc': 16,
    'ic': 17, 'icroom': 17,
}

# Display names for room type selection menus
ROOM_TYPE_NAMES = [
    ('room', '#15 BaseRoom'),
    ('ooc', '#16 OOCRoom'),
    ('ic', '#17 ICRoom'),
]

# ============================================================================
# EXIT TYPES (objnum mappings)
# ============================================================================
#
# Maps user-friendly exit type names (and direction shortcuts) to the
# objnum of the prototype parent object.  Direction names all map to
# ``#21 DirectionalExit``.  Other exit types use progressive objnums.

EXIT_TYPES = {
    # Directional exits (compass directions and vertical movement)
    'dir': 21, 'direction': 21, 'directional': 21,
    'north': 21, 'south': 21, 'east': 21, 'west': 21,
    'ne': 21, 'northeast': 21, 'nw': 21, 'northwest': 21,
    'se': 21, 'southeast': 21, 'sw': 21, 'southwest': 21,
    'u': 21, 'up': 21, 'd': 21, 'down': 21,
    'o': 21, 'out': 21, 'i': 21, 'in': 21,
    # Go exits (keyword-triggered, e.g. "go path")
    'go': 22,
    # Closeable exits (doors that can be opened/closed/locked)
    'door': 23, 'close': 23, 'closeable': 23,
    # Climbable exits (e.g. "climb ladder")
    'climb': 24,
    # Jumpable exits (e.g. "jump gap")
    'jump': 25,
}

# Display names for exit type selection menus
EXIT_TYPE_NAMES = [
    ('dir', '#21 DirectionalExit'),
    ('go', '#22 GoExit'),
    ('door', '#23 ClosableGoExit'),
    ('climb', '#24 ClimbableExit'),
    ('jump', '#25 JumpableExit'),
]

# ============================================================================
# OBJECT TYPES (objnum mappings)
# ============================================================================
#
# Maps user-friendly object type names to the objnum of the prototype
# parent object.  Used by ``@make`` when creating new objects.

TCLASSES = {
    # Generic objects
    'obj': 10, 'object': 10,
    # Containers
    'container': 26, 'box': 27, 'cup': 28,
    # Wearables
    'clothes': 29, 'wearable': 29,
    # Furniture
    'furniture': 30,
}

# ============================================================================
# VOCABULARY CONSTANTS
# ============================================================================
#
# Word lists used by the command parser and matching utilities.

# Prepositions recognized in look commands (``look in box``, ``look
# under table``, etc.).  This is a subset of the full preposition
# table, limited to spatial prepositions that make sense with "look".
LPREPS = ['in', 'on', 'under', 'behind', 'through', 'over', 'across', 'at']

# Valid articles for object names.  The parser strips these from the
# front of object-match strings so that ``take the sword`` matches
# an object named ``sword``.
GOOD_ARTICLES = [
    'a', 'A', 'an', 'An', 'the', 'The',
    'some', 'Some', 'a pair of', 'A Pair of',
    'a set of', 'A Set of', 'a shot glass of', 'A shot glass of',
    'a short glass of', 'A short glass of',
]

# Ordinals for matching "second sword", "third key", etc.  When a
# player types ``take second sword``, the parser extracts the ordinal
# and uses it as a 1-based index into the list of matching objects.
ORDINALS = [
    'first', 'second', 'third', 'fourth', 'fifth',
    'sixth', 'seventh', 'eighth', 'ninth', 'tenth',
    'eleventh', 'twelfth', 'thirteenth', 'fourteenth', 'fifteenth',
]

# ============================================================================
# PERMISSION FLAGS
# ============================================================================

# Royal flag (wizard bit) -- the numeric value of the WIZARD flag in
# the legacy permission model.  Corresponds to ``ObjectFlags.WIZARD``.
ROYALFLAG = 4

# ============================================================================
# SPECIAL CHARACTERS AND TOKENS
# ============================================================================
#
# Single-character prefixes and separators that have special meaning
# in the command parser.

# Command prefixes
BUILTIN_COMMAND_PREFIX = '@'  # @create, @dig, etc.
EVAL_COMMAND_PREFIX = '/'     # Shortcut for eval
EXEC_COMMAND_PREFIX = ';'     # Shortcut for exec (if implemented)

# Object reference prefix -- ``#123`` refers to object 123
OBJECT_REFERENCE_PREFIX = '#'

# Property reference separator -- ``object.property``
PROPERTY_SEPARATOR = '.'

# Verb reference separator -- ``object:verb``
VERB_SEPARATOR = ':'

# ============================================================================
# DEFAULT PERMISSIONS
# ============================================================================
#
# Permission strings assigned to newly-created properties and verbs
# when no explicit permissions are given.
#
# Permission characters:
#   r = readable by anyone
#   w = writable by anyone
#   x = executable by anyone
#   c = inheritable by children (properties only)

# Default property permissions -- readable and inheritable.
DEFAULT_PROPERTY_PERMS = 'rc'

# Default verb permissions -- readable and executable.
DEFAULT_VERB_PERMS = 'rx'

# Default object flags (no flags set)
DEFAULT_OBJECT_FLAGS = 0

# ============================================================================
# ERROR CODES
# ============================================================================
#
# Human-readable descriptions of the standard MOO error codes defined
# in ``moo.properties.MOOError``.  Used by error-reporting utilities
# and the ``@error`` debug command.

# Standard MOO error codes
ERROR_CODES = {
    'E_NONE': 'No error',
    'E_TYPE': 'Type mismatch',
    'E_DIV': 'Division by zero',
    'E_PERM': 'Permission denied',
    'E_PROPNF': 'Property not found',
    'E_VERBNF': 'Verb not found',
    'E_VARNF': 'Variable not found',
    'E_INVIND': 'Invalid indirection',
    'E_RECMOVE': 'Recursive move',
    'E_MAXREC': 'Maximum recursion depth exceeded',
    'E_RANGE': 'Range error',
    'E_ARGS': 'Incorrect number of arguments',
    'E_NACC': 'Move refused by destination',
    'E_INVARG': 'Invalid argument',
    'E_QUOTA': 'Resource quota exceeded',
    'E_FLOAT': 'Floating-point error',
}

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================


def get_preposition_aliases(canonical: str) -> list:
    """
    Get all aliases for a canonical preposition.

    Looks up *canonical* in the ``PREPOSITIONS`` dict and returns every
    surface form that maps to it.

    Args:
        canonical (str): Canonical preposition form (e.g. ``'in'``,
            ``'with'``, ``'='``).

    Returns:
        list[str]: All aliases including the canonical form itself.
            Returns an empty list if *canonical* is not recognized.

    Example::

        >>> get_preposition_aliases('in')
        ['in', 'inside', 'into']
        >>> get_preposition_aliases('nonexistent')
        []
    """
    return PREPOSITIONS.get(canonical, [])


def is_special_preposition(prep: str) -> bool:
    """
    Check if a preposition is special (can be used without whitespace).

    Special prepositions (``=``, ``?``, ``:``) are handled differently
    by the command parser because they may appear glued to their
    operands with no surrounding spaces.

    Args:
        prep (str): Preposition string to check.

    Returns:
        bool: ``True`` if *prep* is in ``SPECIAL_PREPOSITIONS``.

    Example::

        >>> is_special_preposition('=')
        True
        >>> is_special_preposition('in')
        False
    """
    return prep in SPECIAL_PREPOSITIONS


def get_all_preposition_strings() -> list:
    """
    Get a flat list of all preposition strings.

    Returns a copy of ``ALL_PREPOSITIONS`` so callers can modify the
    list without affecting the global constant.

    Returns:
        list[str]: Every recognized preposition surface form.

    Example::

        >>> preps = get_all_preposition_strings()
        >>> 'inside' in preps
        True
    """
    return ALL_PREPOSITIONS.copy()


# ---------------------------------------------------------------------------
#   Password prompts
# ---------------------------------------------------------------------------

#: Matches the login prompts that ask for a password, so a transport can
#: stop the next line of input from being displayed.
#:
#: It lives here rather than in login.py because both transports need it
#: and neither owns it: telnet answers with IAC WILL ECHO, the web client
#: with an echo message to the browser.  Change the wording of a prompt in
#: login.py and this is the thing to re-check.
PASSWORD_PROMPT_RE = re.compile(r'password[^a-z]*:\s*$', re.IGNORECASE)
