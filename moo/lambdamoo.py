"""
Reader for LambdaMOO database files.

This parses the on-disk format LambdaMOO writes -- the one every classic
core ships as, JHCore and LambdaCore included -- into plain Python data.
It does not touch a MegaMOO database; :mod:`moo.lambdamoo_import` does the
mapping.  Keeping the two apart means the parser can be tested against a
real core without creating anything.

The format
----------

A header::

    ** LambdaMOO Database, Format Version 4 **
    <object count>
    <verb program count>
    <unused>
    <player count>
    <player objid> ...          one per line

Then every object in turn, as a fixed run of lines::

    #<objid>                    or "#<objid> recycled"
    <name>
    <blank>                     an obsolete field, always empty
    <flags>                     bit set, see FLAG_* below
    <owner> <location> <contents> <next> <parent> <child> <sibling>
    <verbdef count>
      <name> <owner> <perms> <prep>     four lines each
    <propdef count>
      <name>                            one line each
    <propval count>
      <value> <owner> <perms>           value is 1+ lines, see read_value

``contents``/``next`` and ``child``/``sibling`` are the heads and links of
LambdaMOO's intrusive linked lists.  They are read but not followed: the
parent and location fields on each object say the same thing, and reading
those directly cannot go wrong if a list is malformed.

Then the verb programs, one per verbdef that has code::

    #<objid>:<index>
    <line> ...
    .

A lone ``.`` ends the program; a line of real code that is just ``.`` is
written as ``..``, which this undoes.

Anything after the programs -- queued tasks, suspended tasks, connections --
is deliberately not read.  It describes a *running* server, not a world.

Values
------

Every property value is a type tag on its own line followed by the value.
The tags are LambdaMOO's internal enum and are not stable across major
versions; :data:`TYPE_NAMES` records the ones this understands.  A type
this does not know is a hard error rather than a guess, because guessing
would put silently wrong data in someone's world.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    'LambdaMOOError', 'LambdaObject', 'LambdaVerbDef', 'LambdaDB',
    'parse', 'parse_string',
    'FLAG_USER', 'FLAG_PROGRAMMER', 'FLAG_WIZARD', 'FLAG_READ',
    'FLAG_WRITE', 'FLAG_FERTILE', 'TYPE_NAMES',
]


# --------------------------------------------------------------------------
# Constants from LambdaMOO's structures.h / db_file.c
# --------------------------------------------------------------------------

# Object flag bit positions.  The gaps are real: bits 3 and 6 held flags
# that were removed, and are still skipped so old databases keep working.
FLAG_USER = 0
FLAG_PROGRAMMER = 1
FLAG_WIZARD = 2
FLAG_READ = 4
FLAG_WRITE = 5
FLAG_FERTILE = 7

# Value type tags.
TYPE_INT = 0
TYPE_OBJ = 1
TYPE_STR = 2
TYPE_ERR = 3
TYPE_LIST = 4
TYPE_CLEAR = 5
TYPE_NONE = 6
TYPE_CATCH = 7
TYPE_FINALLY = 8
TYPE_FLOAT = 9

TYPE_NAMES = {
    TYPE_INT: 'int', TYPE_OBJ: 'obj', TYPE_STR: 'str', TYPE_ERR: 'err',
    TYPE_LIST: 'list', TYPE_CLEAR: 'clear', TYPE_NONE: 'none',
    TYPE_CATCH: 'catch', TYPE_FINALLY: 'finally', TYPE_FLOAT: 'float',
}

#: Error values, by their LambdaMOO number.  Kept as names so an imported
#: property holding E_PERM still says E_PERM.
ERROR_NAMES = [
    'E_NONE', 'E_TYPE', 'E_DIV', 'E_PERM', 'E_PROPNF', 'E_VERBNF',
    'E_VARNF', 'E_INVIND', 'E_RECMOVE', 'E_MAXREC', 'E_RANGE', 'E_ARGS',
    'E_NACC', 'E_INVARG', 'E_QUOTA', 'E_FLOAT',
]

#: Verb argument specifiers, indexed by the two-bit field in the perms word.
ARG_SPECS = ['none', 'any', 'this']

# Verb permission bits.
VF_READ = 0o1
VF_WRITE = 0o2
VF_EXEC = 0o4
VF_DEBUG = 0o10
VF_DOBJSHIFT = 4
VF_IOBJSHIFT = 6
VF_OBJMASK = 0o3

# Property permission bits.
PF_READ = 0o1
PF_WRITE = 0o2
PF_CHOWN = 0o4

#: Preposition list, in LambdaMOO's own order -- the stored prep is an
#: index into this.  -1 means "any", -2 means "none".
PREPOSITIONS = [
    'with/using', 'at/to', 'in front of', 'in/inside/into', 'on top of/on/onto/upon',
    'out of/from inside/from', 'over', 'through', 'under/underneath/beneath',
    'behind', 'beside', 'for/about', 'is', 'as', 'off/off of',
]


class LambdaMOOError(Exception):
    """Raised when the file is not a LambdaMOO database this can read."""


# --------------------------------------------------------------------------
# Parsed shapes
# --------------------------------------------------------------------------

@dataclass
class LambdaVerbDef:
    """One verb definition, without its code."""
    names: str                      # space-separated, LambdaMOO's own form
    owner: int
    perms: int
    prep: int
    code: str = ''                  # filled in from the programs section

    @property
    def name_list(self) -> List[str]:
        """The names as a list.  ``*`` is LambdaMOO's min-match marker."""
        return [n for n in self.names.split() if n]

    @property
    def is_executable(self) -> bool:
        return bool(self.perms & VF_EXEC)

    @property
    def dobj(self) -> str:
        return ARG_SPECS[(self.perms >> VF_DOBJSHIFT) & VF_OBJMASK]

    @property
    def iobj(self) -> str:
        return ARG_SPECS[(self.perms >> VF_IOBJSHIFT) & VF_OBJMASK]

    @property
    def prep_name(self) -> str:
        if self.prep == -1:
            return 'any'
        if self.prep == -2 or self.prep < 0:
            return 'none'
        if self.prep < len(PREPOSITIONS):
            return PREPOSITIONS[self.prep]
        return 'any'


@dataclass
class LambdaObject:
    """One object out of the database."""
    objid: int
    recycled: bool = False
    name: str = ''
    flags: int = 0
    owner: int = -1
    location: int = -1
    parent: int = -1
    contents: int = -1
    next: int = -1
    child: int = -1
    sibling: int = -1
    verbs: List[LambdaVerbDef] = field(default_factory=list)
    propdefs: List[str] = field(default_factory=list)
    propvals: List[Tuple[Any, int, int]] = field(default_factory=list)

    def has_flag(self, bit: int) -> bool:
        return bool(self.flags & (1 << bit))

    @property
    def is_player(self) -> bool:
        return self.has_flag(FLAG_USER)

    @property
    def is_wizard(self) -> bool:
        return self.has_flag(FLAG_WIZARD)

    @property
    def is_programmer(self) -> bool:
        return self.has_flag(FLAG_PROGRAMMER)

    @property
    def is_fertile(self) -> bool:
        return self.has_flag(FLAG_FERTILE)


@dataclass
class LambdaDB:
    """A whole parsed database."""
    version: int = 0
    objects: Dict[int, LambdaObject] = field(default_factory=dict)
    players: List[int] = field(default_factory=list)
    declared_objects: int = 0
    declared_verbs: int = 0
    warnings: List[str] = field(default_factory=list)

    @property
    def live_objects(self) -> List[LambdaObject]:
        """Objects that actually exist, in number order."""
        return [self.objects[k] for k in sorted(self.objects)
                if not self.objects[k].recycled]

    def verb_count(self) -> int:
        return sum(len(o.verbs) for o in self.live_objects)

    def coded_verb_count(self) -> int:
        return sum(1 for o in self.live_objects for v in o.verbs if v.code)


# --------------------------------------------------------------------------
# The reader
# --------------------------------------------------------------------------

class _Reader:
    """A line cursor that reports where it was when something went wrong."""

    def __init__(self, text: str):
        # Keep empty lines: the obsolete field after an object's name is one,
        # and so is an empty string property value.
        self.lines = text.split('\n')
        self.pos = 0

    def at_end(self) -> bool:
        return self.pos >= len(self.lines)

    def line(self) -> str:
        if self.at_end():
            raise LambdaMOOError(f"file ended early, at line {self.pos + 1}")
        out = self.lines[self.pos]
        self.pos += 1
        return out

    def peek(self) -> str:
        return '' if self.at_end() else self.lines[self.pos]

    def int(self, what: str) -> int:
        raw = self.line().strip()
        try:
            return int(raw)
        except ValueError:
            raise LambdaMOOError(
                f"line {self.pos}: expected {what}, got {raw!r}")


def read_value(r: _Reader) -> Any:
    """
    Read one property value: a type tag, then the value itself.

    Lists recurse.  ``clear`` -- LambdaMOO's marker for "inherit this from
    the parent" -- comes back as ``None``, which is the same thing MegaMOO
    means by an absent property.
    """
    tag = r.int('a value type')

    if tag == TYPE_INT:
        return r.int('an integer')
    if tag == TYPE_OBJ:
        return ObjRef(r.int('an object number'))
    if tag == TYPE_STR:
        return r.line()
    if tag == TYPE_ERR:
        num = r.int('an error number')
        return ERROR_NAMES[num] if 0 <= num < len(ERROR_NAMES) else f'E_{num}'
    if tag == TYPE_FLOAT:
        raw = r.line().strip()
        try:
            return float(raw)
        except ValueError:
            raise LambdaMOOError(f"line {r.pos}: bad float {raw!r}")
    if tag == TYPE_LIST:
        count = r.int('a list length')
        return [read_value(r) for _ in range(count)]
    if tag in (TYPE_CLEAR, TYPE_NONE):
        return None
    if tag in (TYPE_CATCH, TYPE_FINALLY):
        # Only meaningful inside a running task's stack, which is not read.
        return r.int('a control value')

    raise LambdaMOOError(
        f"line {r.pos}: unknown value type {tag}.  This reader knows "
        f"{sorted(TYPE_NAMES)}; refusing to guess.")


class ObjRef(int):
    """
    An object number *as a value*, distinct from a plain integer.

    LambdaMOO separates ``#123`` from ``123`` and code relies on the
    difference, so the distinction is kept through the import rather than
    flattened to int.
    """
    def __repr__(self):
        return f'#{int(self)}'


def _read_object(r: _Reader, db: LambdaDB) -> Optional[LambdaObject]:
    header = r.line().strip()
    if not header.startswith('#'):
        raise LambdaMOOError(
            f"line {r.pos}: expected an object header, got {header!r}")

    body = header[1:].strip()
    if body.endswith('recycled'):
        objid = int(body.split()[0])
        return LambdaObject(objid=objid, recycled=True)

    obj = LambdaObject(objid=int(body))
    obj.name = r.line()
    r.line()                        # obsolete field, always blank
    obj.flags = r.int('object flags')
    obj.owner = r.int('an owner')
    obj.location = r.int('a location')
    obj.contents = r.int('a contents link')
    obj.next = r.int('a next link')
    obj.parent = r.int('a parent')
    obj.child = r.int('a child link')
    obj.sibling = r.int('a sibling link')

    for _ in range(r.int('a verb count')):
        obj.verbs.append(LambdaVerbDef(
            names=r.line(),
            owner=r.int('a verb owner'),
            perms=r.int('verb permissions'),
            prep=r.int('a verb preposition'),
        ))

    for _ in range(r.int('a property-name count')):
        obj.propdefs.append(r.line())

    for _ in range(r.int('a property-value count')):
        value = read_value(r)
        owner = r.int('a property owner')
        perms = r.int('property permissions')
        obj.propvals.append((value, owner, perms))

    return obj


def _read_programs(r: _Reader, db: LambdaDB) -> None:
    """Attach verb code to the verbdefs it belongs to."""
    while not r.at_end():
        head = r.peek().strip()
        if not head.startswith('#') or ':' not in head:
            # The programs are done; what follows describes a running
            # server rather than a world, and is not read.
            return
        r.line()

        ref = head[1:]
        objpart, _, vpart = ref.partition(':')
        try:
            objid, index = int(objpart), int(vpart)
        except ValueError:
            raise LambdaMOOError(f"line {r.pos}: bad program header {head!r}")

        body: List[str] = []
        while True:
            line = r.line()
            if line.strip() == '.':
                break
            # A code line that is only "." is escaped as ".." on disk.
            body.append(line[1:] if line.startswith('..') else line)

        obj = db.objects.get(objid)
        if obj is None or obj.recycled:
            db.warnings.append(
                f"code for #{objid}:{index}, which is not a live object")
            continue
        if index >= len(obj.verbs):
            db.warnings.append(
                f"code for #{objid}:{index}, which has only "
                f"{len(obj.verbs)} verb(s)")
            continue
        obj.verbs[index].code = '\n'.join(body)


def parse_string(text: str) -> LambdaDB:
    """Parse a database already in memory.  See :func:`parse`."""
    r = _Reader(text)
    db = LambdaDB()

    banner = r.line().strip()
    if 'LambdaMOO Database' not in banner:
        raise LambdaMOOError(
            f"not a LambdaMOO database: the first line is {banner!r}")

    marker = 'Format Version'
    if marker in banner:
        tail = banner.split(marker, 1)[1]
        digits = ''.join(ch for ch in tail if ch.isdigit())
        db.version = int(digits) if digits else 0

    if db.version not in (1, 2, 3, 4):
        raise LambdaMOOError(
            f"format version {db.version} is not supported.  This reads "
            f"versions 1 to 4, which covers LambdaMOO through 1.8.")

    db.declared_objects = r.int('an object count')
    db.declared_verbs = r.int('a verb-program count')
    r.int('the unused field')
    for _ in range(r.int('a player count')):
        db.players.append(r.int('a player object number'))

    for _ in range(db.declared_objects):
        if r.at_end():
            db.warnings.append(
                f"file declared {db.declared_objects} objects but ran out "
                f"after {len(db.objects)}")
            break
        obj = _read_object(r, db)
        if obj is not None:
            db.objects[obj.objid] = obj

    _read_programs(r, db)
    return db


def parse(path: str) -> LambdaDB:
    """
    Read a LambdaMOO database file.

    Args:
        path: The .db file to read.

    Returns:
        A :class:`LambdaDB`.  Anything survivable is recorded in its
        ``warnings`` rather than raised, so a slightly damaged core still
        yields everything that was readable.

    Raises:
        LambdaMOOError: The file is not a LambdaMOO database, is a format
            version this cannot read, or is malformed in a way that would
            make the rest of the parse meaningless.
    """
    with open(path, 'r', errors='replace') as fh:
        return parse_string(fh.read())
