"""
MegaMOO Database Layer
(`moo/database.py`)

This module implements the persistent storage engine for all MOO objects
using SQLite.  It provides ACID transactions, crash recovery via WAL mode,
efficient querying, and a single-file database that replaces the previous
file-per-object JSON storage.

Architecture Overview:
    MegaMOO stores all objects in a fully normalized SQLite database.
    Objects, properties, verbs, players, tickers, and metadata each have
    their own table.  The ``_objects`` in-memory cache provides fast access
    to frequently-used objects, with automatic SQLite fallback for cache
    misses.

    Children and contents lists are NOT stored directly — they are derived
    from the ``parent`` and ``location`` columns via indexed queries.  This
    eliminates data duplication and keeps the containment graph consistent.

Key Classes:
    - ``Database``        -- The main entry point.  Create, load, save,
      checkpoint, and query MOO objects.
    - ``DatabaseIndex``   -- Tracks the next available objnum, recycled
      object numbers, and global metadata.

Typical Usage::

    db = Database('game.sqlite', mode='readwrite')
    db.load()

    obj = db.create_object(parent=10, owner=1)
    obj.noun = "sword"
    db.save_object(obj)

    db.checkpoint()
    db.close()

Thread Safety:
    All public methods on ``Database`` are protected by a reentrant lock
    (``threading.RLock``).  SQLite is configured with WAL mode for
    concurrent read access.

Copyright (c) 2026
License: MIT
"""

import json
import logging
import shutil
import sqlite3
import threading
import time
import weakref
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set

from .globals import OBJECT_CACHE_SIZE
from .objects import MOOObject, ObjectFlags
from .properties import MOOObjectRef, MOOError

logger = logging.getLogger('megamoo.database')


# ============================================================================
# SQL SCHEMA
# ============================================================================

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS objects (
    objnum    INTEGER PRIMARY KEY,
    parent    INTEGER NOT NULL DEFAULT 0,
    noun      TEXT    NOT NULL DEFAULT '',
    aliases   TEXT    NOT NULL DEFAULT '[]',
    owner     INTEGER NOT NULL DEFAULT 0,
    location  INTEGER NOT NULL DEFAULT 0,
    flags     INTEGER NOT NULL DEFAULT 0,
    created   REAL    NOT NULL,
    last_move REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_objects_parent   ON objects(parent);
CREATE INDEX IF NOT EXISTS idx_objects_location ON objects(location);
CREATE INDEX IF NOT EXISTS idx_objects_owner    ON objects(owner);

CREATE TABLE IF NOT EXISTS properties (
    objnum  INTEGER NOT NULL,
    name    TEXT    NOT NULL,
    value   TEXT,
    owner   INTEGER NOT NULL DEFAULT 0,
    perms   TEXT    NOT NULL DEFAULT 'rc',
    PRIMARY KEY (objnum, name),
    FOREIGN KEY (objnum) REFERENCES objects(objnum) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS verbs (
    objnum      INTEGER NOT NULL,
    position    INTEGER NOT NULL,
    names       TEXT    NOT NULL,
    code        TEXT    NOT NULL DEFAULT '',
    owner       INTEGER NOT NULL DEFAULT 0,
    perms       TEXT    NOT NULL DEFAULT 'rx',
    parent_type TEXT    NOT NULL DEFAULT 'moo.verb_types.MasterVerb',
    min_lengths TEXT    NOT NULL DEFAULT '{}',
    hidden      INTEGER NOT NULL DEFAULT 0,
    auth        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (objnum, position),
    FOREIGN KEY (objnum) REFERENCES objects(objnum) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS players (
    name   TEXT    PRIMARY KEY,
    objnum INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tickers (
    objnum    INTEGER NOT NULL,
    idstring  TEXT    NOT NULL,
    interval  REAL    NOT NULL,
    verb_name TEXT    NOT NULL,
    PRIMARY KEY (objnum, idstring)
);

CREATE TABLE IF NOT EXISTS recycled_objects (
    objnum INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS reserved_objects (
    objnum INTEGER PRIMARY KEY
);
"""


# ============================================================================
# DATABASE INDEX
# ============================================================================


@dataclass
class DatabaseIndex:
    """
    In-memory index tracking object-number allocation and global metadata.

    Backed by the ``metadata`` table in SQLite.  Loaded once at startup
    and saved on every mutation to ensure crash consistency.

    Attributes:
        next_objnum (int):
            The next object number that ``create_object`` will consider.
        object_count (int):
            Total number of live (non-recycled) objects in the database.
        max_object (int):
            Highest object number that has ever been assigned.
        recycled_objects (Set[int]):
            Object numbers available for reuse.
        reserved_objects (Set[int]):
            Object numbers reserved and not assignable.
        created (float):
            Unix timestamp when the database was first created.
        last_checkpoint (float):
            Unix timestamp of the most recent checkpoint.
        version (str):
            Database format version string.
    """
    next_objnum: int = 1
    object_count: int = 0
    max_object: int = 0
    recycled_objects: Set[int] = field(default_factory=set)
    reserved_objects: Set[int] = field(default_factory=set)
    created: float = field(default_factory=time.time)
    last_checkpoint: float = field(default_factory=time.time)
    version: str = '2.0'

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the index to a JSON-compatible dictionary."""
        return {
            'next_objnum': self.next_objnum,
            'object_count': self.object_count,
            'max_object': self.max_object,
            'recycled_objects': list(self.recycled_objects),
            'reserved_objects': list(self.reserved_objects),
            'created': self.created,
            'last_checkpoint': self.last_checkpoint,
            'version': self.version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DatabaseIndex':
        """Reconstruct a ``DatabaseIndex`` from a dictionary."""
        return cls(
            next_objnum=data.get('next_objnum', 1),
            object_count=data.get('object_count', 0),
            max_object=data.get('max_object', 0),
            recycled_objects=set(data.get('recycled_objects', [])),
            reserved_objects=set(data.get('reserved_objects', [])),
            created=data.get('created', time.time()),
            last_checkpoint=data.get('last_checkpoint', time.time()),
            version=data.get('version', '2.0'),
        )


# ============================================================================
# MAIN DATABASE CLASS
# ============================================================================


class Database:
    """
    The central object database for MegaMOO, backed by SQLite.

    ``Database`` provides the complete lifecycle for MOO objects:
    creation, retrieval, mutation, deletion (recycling), persistence,
    checkpointing, and crash recovery.

    Objects are stored in a normalized SQLite database and cached in
    memory.  SQLite WAL mode provides crash recovery and concurrent
    read access.

    Access Modes:
        - ``'readonly'``  -- No writes allowed.
        - ``'readwrite'`` -- Normal operation.
        - ``'create'``    -- Create a brand-new empty database.

    Typical Lifecycle::

        db = Database('game.sqlite', mode='readwrite')
        db.load()
        obj = db.create_object(10, 1)
        obj.noun = "sword"
        db.save_object(obj)
        db.checkpoint()
        db.close()
    """

    def __init__(self, path: str, mode: str = 'readwrite'):
        """
        Initialize the database (but do not load it yet).

        Call ``load()`` after construction to actually read objects.

        Args:
            path (str): Filesystem path to the SQLite database file
                (e.g. ``'game.sqlite'``).
            mode (str): Access mode -- ``'readonly'``, ``'readwrite'``,
                or ``'create'``.

        Raises:
            ValueError: If *mode* is not one of the three valid strings.
        """
        if mode not in ('readonly', 'readwrite', 'create'):
            raise ValueError(f"Invalid mode: {mode}")

        self.path = Path(path)
        self.mode = mode

        # ----- Checkpoint directory (alongside the .sqlite file) -----
        self.checkpoint_dir = self.path.parent / (self.path.stem + '_checkpoints')
        # How many to keep.  run_server overwrites this from
        # database.max_checkpoints, which was validated at startup and then
        # never reached the pruner -- it took its own hardcoded default, so
        # raising the setting still left you with ten.
        self.max_checkpoints = 10

        # ----- SQLite connection -----
        self._conn: Optional[sqlite3.Connection] = None

        # ----- In-memory structures -----
        self._objects: Dict[int, MOOObject] = {}       # objnum -> MOOObject cache
        self._players: Dict[str, int] = {}             # player_name (lower) -> objnum
        self._index = DatabaseIndex()

        # ----- Object cache tuning -----
        self._cache_size = OBJECT_CACHE_SIZE   # Max objects held in memory
        self._cache_hits = 0
        self._cache_misses = 0

        # True while a verb is running: writes still happen, but the
        # commit is held until the verb finishes so it lands whole or
        # not at all.  Safe as a plain attribute rather than thread-local
        # because the baton allows only one writer at a time.
        self._deferring = False

        #: Objects written during the current verb transaction, so a
        #: rollback knows whose in-memory state to put back.
        self._txn_objects = set()

        # Identity map: every object handed out, for as long as anything
        # still holds a reference to it.
        #
        # `_objects` is a *bounded* cache, so it evicts.  Eviction alone
        # was enough to split an object in two: verb code keeps `pobj`,
        # `this` and `dobj` live across a whole verb body, and if the
        # objnum was evicted mid-body a later get_object() built a second
        # instance of the same object.  Two instances, each writing the
        # whole row on save, silently discarded each other's changes.
        #
        # Weak values, so this map costs nothing once the last real
        # reference goes away and never keeps the world in memory.
        self._live: 'weakref.WeakValueDictionary[int, MOOObject]' = \
            weakref.WeakValueDictionary()

        # ----- Inheritance cache stats -----
        self._inheritance_cache_builds = 0
        self._inheritance_cache_invalidations = 0

        # Mutation generation counter -- bumped on every create / save /
        # recycle.  Used by ``SearchIndex`` to detect stale indexes.
        self._mutation_gen = 0

        # ----- Thread safety -----
        self._lock = threading.RLock()

        logger.info(f"Initialized database at {path} in {mode} mode")

    # ========================================================================
    # SQLite CONNECTION MANAGEMENT
    # ========================================================================

    def _open_connection(self):
        """Open the SQLite connection and set PRAGMAs."""
        self._conn = sqlite3.connect(
            str(self.path),
            check_same_thread=False,
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA synchronous=NORMAL")

    def _create_schema(self):
        """Create all tables and indexes if they don't exist."""
        self._conn.executescript(SCHEMA_SQL)

    # ========================================================================
    # DATABASE LIFECYCLE (load / save / close / checkpoint)
    # ========================================================================

    def load(self):
        """
        Load the database into memory.

        Steps:
            1. Open SQLite connection with WAL mode.
            2. Load metadata from the ``metadata`` table.
            3. Load recycled/reserved sets.
            4. Load player mappings.
            5. Preload objects into the cache.

        If the database was opened in ``'create'`` mode, a fresh empty
        database is initialized instead.

        Raises:
            FileNotFoundError: If the database file does not exist
                and mode is not ``'create'``.
        """
        if self.mode == 'create':
            self._create_new_database()
            return

        if not self.path.exists():
            raise FileNotFoundError(f"Database not found: {self.path}")

        logger.info(f"Loading database from {self.path}")

        self._open_connection()

        # Load metadata
        self._load_metadata()

        # Load recycled/reserved from their tables
        self._load_recycled_reserved()

        # Load players
        self._load_players()

        # Load objects into cache
        self._load_objects()

        logger.info(
            f"Loaded database: {self._index.object_count} objects, "
            f"{len(self._players)} players"
        )

    def save(self):
        """
        Flush all pending changes to the database.

        Saves the metadata and any objects marked with ``_pending_save``.
        SQLite WAL mode handles durability automatically.

        Does nothing in ``'readonly'`` mode.
        """
        if self.mode == 'readonly':
            logger.warning("Cannot save database in readonly mode")
            return

        logger.info("Saving database...")

        with self._lock:
            # Save metadata
            self._save_metadata()

            # Save modified objects
            saved_count = 0
            for objnum, obj in self._objects.items():
                if getattr(obj, '_pending_save', False):
                    self._save_object_to_sql(obj)
                    obj._pending_save = False
                    saved_count += 1

            self._conn.commit()

        logger.info(f"Saved {saved_count} modified objects (of {len(self._objects)} cached)")

    def checkpoint_wal(self) -> bool:
        """
        Fold the write-ahead log back into the database file.

        Distinct from :meth:`checkpoint`, which copies the whole database
        to a timestamped backup.  This one moves committed pages out of
        the ``-wal`` sidecar so the ``.db`` on disk *is* the world -- what
        matters before a restart, a copy, or a commit, since the sidecar
        is not tracked and a stale ``.db`` looks complete.

        Returns:
            bool: True if the checkpoint ran, False if there was no
            connection or SQLite refused (a reader can block it).
        """
        if not self._conn:
            return False
        try:
            with self._lock:
                self._conn.commit()
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return True
        except sqlite3.Error as e:
            logger.warning("WAL checkpoint failed: %s", e)
            return False

    def close(self):
        """
        Close the database, flushing any pending changes first.

        After calling ``close()`` the database instance should not be
        used further.
        """
        if self.mode != 'readonly':
            self.save()
            # Leave the .db self-contained rather than half in a sidecar.
            self.checkpoint_wal()
        if self._conn:
            self._conn.close()
            self._conn = None
        logger.info("Database closed")

    def checkpoint(self):
        """
        Create a backup copy of the SQLite database.

        Uses ``sqlite3.Connection.backup()`` to create a consistent
        snapshot in a timestamped ``.sqlite`` file in the checkpoint
        directory.

        Old checkpoints beyond ``MAX_CHECKPOINT_BACKUPS`` are pruned
        automatically.

        Does nothing in ``'readonly'`` mode.
        """
        if self.mode == 'readonly':
            logger.warning("Cannot checkpoint database in readonly mode")
            return

        logger.info("Creating checkpoint...")

        # Save current state first
        self.save()

        # Create checkpoint directory
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        checkpoint_file = self.checkpoint_dir / f'checkpoint_{timestamp}.sqlite'

        # Use SQLite's built-in backup for a consistent snapshot
        backup_conn = sqlite3.connect(str(checkpoint_file))
        self._conn.backup(backup_conn)
        backup_conn.close()

        # Update checkpoint timestamp
        self._index.last_checkpoint = time.time()
        self._save_metadata()
        self._conn.commit()

        logger.info(f"Checkpoint created: {checkpoint_file}")

        # Clean old checkpoints
        self._prune_old_checkpoints()

    def _prune_old_checkpoints(self, max_checkpoints: Optional[int] = None):
        """Remove old checkpoint files, keeping the most recent ones."""
        if max_checkpoints is None:
            max_checkpoints = self.max_checkpoints
        if not self.checkpoint_dir.exists():
            return
        # Sorted by name, which is why the timestamp in it has to be real:
        # while every checkpoint was called checkpoint_&Y&m&d_&H&M&S.sqlite
        # this pruned a list of one, forever.
        checkpoints = sorted(self.checkpoint_dir.glob('checkpoint_*.sqlite'))
        while len(checkpoints) > max_checkpoints:
            oldest = checkpoints.pop(0)
            oldest.unlink()
            logger.info(f"Removed old checkpoint: {oldest}")

    # ========================================================================
    # OBJECT MANAGEMENT
    # ========================================================================

    def get_object(self, objnum: int) -> MOOObject:
        """
        Retrieve an object by its object number.

        The object is served from the in-memory cache if available;
        otherwise it is loaded from SQLite and added to the cache.
        If the cache is full, the least-recently-inserted object is
        evicted (saving it first if dirty).

        Args:
            objnum (int): The object number to look up.

        Returns:
            MOOObject: The requested object.

        Raises:
            KeyError: If no object with the given number exists.
        """
        with self._lock:
            # Check cache first
            if objnum in self._objects:
                self._cache_hits += 1
                obj = self._objects[objnum]
                if obj._database is None:
                    obj._database = self
                return obj

            # Evicted from the bounded cache, but still alive somewhere?
            # Then that instance *is* the object, and loading a second
            # copy would fork it.  Promote the existing one instead.
            live = self._live.get(objnum)
            if live is not None:
                self._cache_hits += 1
                if live._database is None:
                    live._database = self
                self._admit(objnum, live)
                return live

            # Cache miss -- load from SQLite
            self._cache_misses += 1
            obj = self._load_object_from_sql(objnum)

            # Set database reference and enable auto-save
            obj._database = self
            obj.enable_auto_save(self)

            self._admit(objnum, obj)
            return obj

    def _admit(self, objnum: int, obj: MOOObject) -> None:
        """
        Put *obj* in the bounded cache, evicting to make room.

        Also records it in the identity map, which is what guarantees
        that an eviction can never hand out a second instance of an
        object something else is still holding.

        Args:
            objnum (int): The object's number.
            obj (MOOObject): The instance to cache.
        """
        # Never evict down to nothing, and never evict the object we are
        # admitting: `>=` on a full cache pops before inserting.
        while len(self._objects) >= self._cache_size:
            evict_key = next(iter(self._objects))
            if evict_key == objnum:
                break
            evicted = self._objects.pop(evict_key)
            if getattr(evicted, '_pending_save', False):
                self._save_object_to_sql(evicted)

        self._objects[objnum] = obj
        self._live[objnum] = obj

    def create_object(self, parent: int = 0, owner: int = 0) -> MOOObject:
        """
        Create a new MOO object and persist it to SQLite.

        The new object is assigned the lowest unused object number that
        is not reserved.  If recycled numbers are available, the lowest
        one is reused.

        Args:
            parent (int): Object number of the parent (prototype).
            owner (int): Object number of the owner.

        Returns:
            MOOObject: The newly created object.

        Raises:
            PermissionError: If the database is in ``'readonly'`` mode.
        """
        if self.mode == 'readonly':
            raise PermissionError("Cannot create object in readonly mode")

        with self._lock:
            # Find the lowest unused, unreserved object number.
            #
            # A recycled number is additionally checked for traces before
            # it is handed out again.  _clear_refs_to erased the scalar
            # '#N' references at recycle time, but an objnum sitting as a
            # bare integer in some list cannot be told apart from an
            # index or a plain number, so it is not safe to erase -- and
            # reissuing the number under it would make that integer start
            # naming the wrong object.  Skipping the number costs one
            # objnum and settles the question.
            #
            # Only recycled candidates pay for the scan; a fresh number
            # off the end has nothing pointing at it by definition.
            reserved = self._index.reserved_objects
            recycled = self._index.recycled_objects
            objnum = 0
            while (objnum in self._objects
                   or objnum in reserved
                   or self._object_exists_in_sql(objnum)
                   or (objnum in recycled and self._refs_block_reuse(objnum))):
                objnum += 1
            if objnum >= self._index.next_objnum:
                self._index.next_objnum = objnum + 1
            self._index.recycled_objects.discard(objnum)

            # Remove from recycled_objects table if present
            self._conn.execute(
                "DELETE FROM recycled_objects WHERE objnum = ?", (objnum,)
            )

            # Create object
            obj = MOOObject(objnum=objnum, parent=parent, owner=owner)

            # Set database reference and enable auto-save
            obj._database = self
            obj.enable_auto_save(self)

            # Update index
            self._index.object_count += 1
            self._index.max_object = max(self._index.max_object, objnum)

            # Add to cache
            self._admit(objnum, obj)

            # Save to SQLite immediately
            self._save_object_to_sql(obj)
            self._save_metadata()
            self._conn.commit()

            # Update parent's children set
            if parent > 0:
                try:
                    parent_obj = self.get_object(parent)
                    parent_obj.children.add(objnum)
                    self.save_object(parent_obj)
                except KeyError:
                    logger.warning(f"Parent object #{parent} not found")

            logger.debug(f"Created object #{objnum}")
            self._mutation_gen += 1
            return obj

    def _create_object_with_objnum(self, objnum: int, parent: int = 0,
                                   owner: int = 0) -> MOOObject:
        """
        Create an object at a specific objnum (for bootstrap).

        This bypasses normal number allocation and forces the given
        objnum.  Used only by bootstrap.py to create object #0.

        Args:
            objnum (int): The specific object number to assign.
            parent (int): Parent object number.
            owner (int): Owner object number.

        Returns:
            MOOObject: The newly created object.
        """
        with self._lock:
            self._index.recycled_objects.discard(objnum)
            self._conn.execute(
                "DELETE FROM recycled_objects WHERE objnum = ?", (objnum,)
            )

            obj = MOOObject(objnum=objnum, parent=parent, owner=owner)
            obj._database = self
            obj.enable_auto_save(self)

            self._index.object_count += 1
            self._index.max_object = max(self._index.max_object, objnum)
            if objnum >= self._index.next_objnum:
                self._index.next_objnum = objnum + 1

            self._admit(objnum, obj)

            self._save_object_to_sql(obj)
            self._save_metadata()
            self._conn.commit()

            logger.debug(f"Created object #{objnum} (forced)")
            self._mutation_gen += 1
            return obj

    def reserve_objects(self, start: int, end: int):
        """
        Reserve a range of object numbers so ``create_object`` skips them.

        Args:
            start (int): First object number in the range (inclusive).
            end (int): Last object number in the range (inclusive).
        """
        for n in range(start, end + 1):
            self._index.reserved_objects.add(n)
            self._conn.execute(
                "INSERT OR IGNORE INTO reserved_objects (objnum) VALUES (?)",
                (n,)
            )
        self._save_metadata()
        self._conn.commit()

    def unreserve_objects(self, start: int, end: int):
        """
        Unreserve a range of object numbers.

        Args:
            start (int): First object number in the range (inclusive).
            end (int): Last object number in the range (inclusive).
        """
        for n in range(start, end + 1):
            self._index.reserved_objects.discard(n)
            self._conn.execute(
                "DELETE FROM reserved_objects WHERE objnum = ?", (n,)
            )
        self._save_metadata()
        self._conn.commit()

    @staticmethod
    def _mentions_objnum(value, objnum: int) -> bool:
        """
        Does *value* contain *objnum* as a bare integer, nested anywhere?

        Only the integer form.  A scalar ``'#N'`` string is a reference
        the engine itself resolves, and :meth:`_clear_refs_to` erases
        those outright; this looks for the form it cannot safely touch.

        Args:
            value: A decoded property value.
            objnum (int): The object number to look for.

        Returns:
            bool: True if the number appears as an int somewhere inside.
        """
        if isinstance(value, bool):
            return False                      # bool is an int subclass
        if isinstance(value, int):
            return value == objnum
        if isinstance(value, list):
            return any(Database._mentions_objnum(v, objnum) for v in value)
        if isinstance(value, dict):
            return any(Database._mentions_objnum(v, objnum)
                       for v in value.values())
        return False

    def _clear_refs_to(self, objnum: int) -> int:
        """
        Erase every scalar ``'#N'`` reference to a recycled object.

        A property whose whole value is ``'#500'`` is auto-resolved on
        read (:meth:`MOOObject._resolve_objref`).  Left in place across a
        recycle it did something worse than dangle: once #500 was handed
        out again, the property silently started resolving to a
        completely unrelated live object, and nothing raised.

        Only the scalar string form is touched, because only that form is
        unambiguously a reference.  An integer inside a list may be an
        objnum, but it may equally be an index -- ``obvexits`` holds
        indices into ``dnames`` -- and there is nothing in the value to
        tell them apart.  Those are handled by refusing to reissue the
        number instead; see :meth:`_lingering_refs`.

        Args:
            objnum (int): The object number being recycled.

        Returns:
            int: How many properties were cleared.
        """
        token = json.dumps(f'#{objnum}')
        rows = self._conn.execute(
            "SELECT objnum, name FROM properties WHERE value = ?", (token,)
        ).fetchall()
        for owner_num, name in rows:
            self._conn.execute(
                "UPDATE properties SET value = ? WHERE objnum = ? AND name = ?",
                (json.dumps(None), owner_num, name)
            )
            # Keep any instance already in memory in step, or it would go
            # on serving the old string and write it back on next save.
            cached = self._objects.get(owner_num) or self._live.get(owner_num)
            info = getattr(cached, 'properties', {}).get(name) if cached else None
            if info is not None:
                info.value = None
        if rows:
            logger.info("Cleared %d reference(s) to recycled #%s", len(rows), objnum)
        return len(rows)

    def _lingering_refs(self, objnum: int):
        """
        Find properties that still mention *objnum* as a bare integer.

        Used to decide whether a recycled number is safe to hand out
        again.  It is cheaper than it looks: the ``LIKE`` prefilter
        rejects almost everything before any JSON is parsed, and this
        only runs for numbers that are actually being reused.

        Args:
            objnum (int): The candidate number.

        Returns:
            list[tuple[int, str]]: ``(objnum, property_name)`` pairs.
        """
        rows = self._conn.execute(
            "SELECT objnum, name, value FROM properties WHERE value LIKE ?",
            (f'%{objnum}%',)
        ).fetchall()
        hits = []
        for owner_num, name, raw in rows:
            try:
                decoded = json.loads(raw) if raw is not None else None
            except (ValueError, TypeError):
                continue
            if self._mentions_objnum(decoded, objnum):
                hits.append((owner_num, name))
        return hits

    def _refs_block_reuse(self, objnum: int) -> bool:
        """
        Is it unsafe to hand *objnum* out again?

        True when something still mentions the number as a bare integer.
        Logged rather than silent: a number that keeps being skipped is
        usually a list somebody forgot to tidy, and that is worth being
        able to see.

        Args:
            objnum (int): The candidate number.

        Returns:
            bool: True if the number should be skipped.
        """
        hits = self._lingering_refs(objnum)
        if hits:
            where = ', '.join(f'#{o}.{n}' for o, n in hits[:5])
            logger.info("Not reusing #%s; still referenced by %s%s",
                        objnum, where, ' ...' if len(hits) > 5 else '')
        return bool(hits)

    def recycle_object(self, objnum: int):
        """
        Delete an object and mark its number for future reuse.

        Uses DELETE CASCADE to remove the object and all its properties
        and verbs in a single transaction.

        Args:
            objnum (int): The object number to recycle.

        Raises:
            KeyError: If the object does not exist.
            ValueError: If the object still has children or contents.
            PermissionError: If the database is in ``'readonly'`` mode.
        """
        if self.mode == 'readonly':
            raise PermissionError("Cannot recycle object in readonly mode")

        with self._lock:
            obj = self.get_object(objnum)

            # Guard: cannot recycle objects that still have dependents
            if obj.children:
                raise ValueError(
                    f"Cannot recycle #{objnum}: has children {obj.children}"
                )
            if obj._content_ids:
                raise ValueError(
                    f"Cannot recycle #{objnum}: has contents {obj._content_ids}"
                )

            # Past the guards, so nothing below can bail out and leave the
            # world half-swept.  Pointers *to* the object go before the
            # object does: reusing a number is fine, but reusing one that
            # something still points at is exactly how a stale reference
            # turns into a valid pointer to an unrelated object.
            self._clear_refs_to(objnum)

            # Remove from parent's children set
            if obj.parent > 0:
                try:
                    parent = self.get_object(obj.parent)
                    parent.children.discard(objnum)
                    self.save_object(parent)
                except KeyError:
                    pass

            # Remove from location's contents list
            if obj._location_id > 0:
                try:
                    location = self.get_object(obj._location_id)
                    if objnum in location._content_ids:
                        location._content_ids.remove(objnum)
                    self.save_object(location)
                except KeyError:
                    pass

            # Remove from in-memory cache, and from the identity map with
            # it.  The map exists to stop a second instance being built
            # for a number that is still live; a *recycled* number is the
            # opposite case -- if this number is later reissued to a new
            # object, anything still clutching the dead one must not be
            # handed back as the new one's identity.
            if objnum in self._objects:
                del self._objects[objnum]
            self._live.pop(objnum, None)

            # DELETE CASCADE removes object + properties + verbs
            self._conn.execute(
                "DELETE FROM objects WHERE objnum = ?", (objnum,)
            )

            # Add to recycled set
            self._index.recycled_objects.add(objnum)
            self._index.object_count -= 1
            self._conn.execute(
                "INSERT OR IGNORE INTO recycled_objects (objnum) VALUES (?)",
                (objnum,)
            )

            self._save_metadata()
            self._conn.commit()

            logger.debug(f"Recycled object #{objnum}")
            self._mutation_gen += 1

    def save_object(self, obj: MOOObject):
        """
        Persist a single object to SQLite.

        The object is also updated in the in-memory cache.

        Args:
            obj (MOOObject): The object to save.

        Note:
            Does nothing silently if the database is in ``'readonly'``
            mode.
        """
        if self.mode == 'readonly':
            return

        # The baton before the database lock, always in that order, so
        # this can never deadlock against a verb which takes them the
        # same way round.  A write from outside verb execution -- the
        # API, a login -- would otherwise commit whatever a running verb
        # had pending, since they share one connection.
        from . import verb_baton
        with verb_baton.exclusive():
            with self._lock:
                # Update cache (and the identity map, via _admit)
                self._admit(obj.objnum, obj)

                # Save to SQLite
                self._save_object_to_sql(obj)
                # Held back while a verb is running: the verb commits as
                # a whole, or rolls back as a whole.
                if self._deferring:
                    self._txn_objects.add(obj.objnum)
                else:
                    self._conn.commit()
                self._mutation_gen += 1

    # ------------------------------------------------------------------
    # Verb transactions
    # ------------------------------------------------------------------

    def begin_verb_txn(self):
        """
        Stop committing on each write until the verb finishes.

        A verb that raised halfway used to leave everything it had
        already written -- half a trade, a debited purse and no goods.
        Deferring the commit makes the verb the unit that succeeds or
        fails, which is the one idea worth taking from mooR's
        transactional model without adopting the rest of it.
        """
        self._deferring = True
        self._txn_objects = set()

    def commit_verb_txn(self):
        """Commit everything the verb wrote and resume normal commits."""
        self._deferring = False
        self._txn_objects = set()
        if self._conn:
            self._conn.commit()

    def rollback_verb_txn(self):
        """
        Discard everything the verb wrote and resume normal commits.

        Rolling back SQLite is only half of it.  The objects live in
        memory as well, still holding the values the verb assigned, and
        the identity map hands out those same instances -- so evicting
        them from the cache would not help, and the next save would write
        the rolled-back values straight back. Each touched object has its
        state read again from disk, in place, so memory and database say
        the same thing.
        """
        self._deferring = False
        touched, self._txn_objects = self._txn_objects, set()
        if self._conn:
            try:
                self._conn.rollback()
            except sqlite3.Error as e:
                logger.warning("Verb rollback failed: %s", e)
        for objnum in touched:
            self._revert_object(objnum)

    def _revert_object(self, objnum: int):
        """
        Put one object's in-memory state back to what is on disk.

        Refreshes the *existing* instance rather than replacing it: verb
        code is still holding references to it, and the identity map
        exists precisely so there is only ever one.

        Args:
            objnum (int): Object to revert.
        """
        live = self._objects.get(objnum) or self._live.get(objnum)
        if live is None:
            return
        try:
            fresh = self._load_object_from_sql(objnum)
        except KeyError:
            # It was created inside the rolled-back transaction, so on
            # disk it never existed.  Drop it rather than leave a ghost.
            self._objects.pop(objnum, None)
            self._live.pop(objnum, None)
            return
        d = live.__dict__
        d['properties'] = fresh.properties
        d['verbs'] = fresh.verbs
        for field in ('parent', 'noun', 'aliases', 'owner', 'flags',
                      'created', 'last_move', '_location_id'):
            d[field] = fresh.__dict__[field]
        d['_dirty_props'] = set()
        d['_all_dirty'] = False
        try:
            live.invalidate_inheritance_cache()
        except Exception:
            pass

    # ========================================================================
    # INHERITANCE CACHE MANAGEMENT
    # ========================================================================

    def invalidate_descendant_caches(self, objnum: int):
        """
        Invalidate inheritance caches for an object and all its descendants.

        Args:
            objnum (int): Root object number to start invalidation from.
        """
        try:
            obj = self.get_object(objnum)
            obj.invalidate_inheritance_cache(self)
            self._inheritance_cache_invalidations += 1
        except KeyError:
            pass

    def invalidate_all_caches(self):
        """Invalidate all inheritance caches in the entire database."""
        with self._lock:
            for obj in self._objects.values():
                obj._inheritance_cache_valid = False
                obj._resolved_properties = None
                obj._resolved_verbs = None
                obj._cache_dirty = True
            self._inheritance_cache_invalidations += 1
            logger.info("Invalidated all inheritance caches")

    def cache_stats(self) -> Dict[str, Any]:
        """Return diagnostic cache-performance statistics."""
        cached_objects = len(self._objects)
        valid_caches = sum(
            1 for obj in self._objects.values()
            if obj._inheritance_cache_valid
        )
        return {
            'object_cache_size': cached_objects,
            'object_cache_hits': self._cache_hits,
            'object_cache_misses': self._cache_misses,
            'inheritance_caches_valid': valid_caches,
            'inheritance_caches_invalid': cached_objects - valid_caches,
            'inheritance_cache_builds': self._inheritance_cache_builds,
            'inheritance_cache_invalidations': self._inheritance_cache_invalidations,
        }

    # ========================================================================
    # QUERIES
    # ========================================================================

    def valid(self, objnum: int) -> bool:
        """
        Check whether an object number refers to a live object.

        Args:
            objnum (int): Object number to check.

        Returns:
            bool: ``True`` if the object exists and can be loaded.
        """
        try:
            self.get_object(objnum)
            return True
        except KeyError:
            return False

    def max_object(self) -> int:
        """Return the highest object number that has ever been assigned."""
        return self._index.max_object

    def objects(self) -> Iterator[MOOObject]:
        """
        Iterate over every live object in the database.

        Queries the ``objects`` table in ascending objnum order.

        Yields:
            MOOObject: Each live object, in ascending objnum order.
        """
        rows = self._conn.execute(
            "SELECT objnum FROM objects ORDER BY objnum"
        ).fetchall()
        for (objnum,) in rows:
            if objnum not in self._index.recycled_objects:
                try:
                    yield self.get_object(objnum)
                except Exception as e:
                    logger.error(f"Error loading object #{objnum}: {e}")

    # ========================================================================
    # PLAYER MANAGEMENT
    # ========================================================================

    def add_player(self, name: str, objnum: int):
        """
        Register a player name -> object number mapping.

        Args:
            name (str): Player display name.
            objnum (int): The player's object number.
        """
        self._players[name.lower()] = objnum
        if self.mode != 'readonly':
            self._conn.execute(
                "INSERT OR REPLACE INTO players (name, objnum) VALUES (?, ?)",
                (name.lower(), objnum)
            )
            self._conn.commit()

    def get_player(self, name: str) -> Optional[int]:
        """
        Look up a player's object number by name.

        Args:
            name (str): Player name (case-insensitive).

        Returns:
            int or None: The player's object number, or ``None``.
        """
        return self._players.get(name.lower())

    def remove_player(self, name: str):
        """
        Remove a player name registration.

        Args:
            name (str): Player name to unregister (case-insensitive).
        """
        if name.lower() in self._players:
            del self._players[name.lower()]
            if self.mode != 'readonly':
                self._conn.execute(
                    "DELETE FROM players WHERE name = ?", (name.lower(),)
                )
                self._conn.commit()

    def players_list(self) -> List[str]:
        """Get a list of all registered player names (lower-cased)."""
        return list(self._players.keys())

    def connected_players(self) -> List[int]:
        """
        Registered players carrying the PLAYER flag, by object number.

        The flag is a *mirror* of the connection table -- the engine sets it
        at login and clears it at disconnect -- so in practice this answers
        the same question as the connection table itself. It is not the same
        source, though, and a mirror can drift where the table cannot.

        **Ask ``builtins.connected_players()`` for who is attached.** It
        reads ``_player_connections`` directly, covers telnet, the web
        client and virtual bots alike, and hands back objects. This stays as
        the database-layer flag query it has always been; nothing in the
        engine now uses it to decide who is online.

        Returns:
            list[int]: Object numbers of players with the PLAYER flag.
        """
        connected = []
        for objnum in self._players.values():
            try:
                obj = self.get_object(objnum)
                if obj.is_player:
                    connected.append(objnum)
            except Exception:
                pass
        return connected

    # ========================================================================
    # INTERNAL / PRIVATE METHODS
    # ========================================================================

    def _create_new_database(self):
        """
        Initialize a brand-new empty database.

        Creates the SQLite file and schema with empty tables.
        Objects are created by the caller (e.g. ``bootstrap.py``).
        """
        logger.info(f"Creating new database at {self.path}")

        # Ensure parent directory exists
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self._open_connection()
        self._create_schema()

        # Empty database -- next_objnum starts at 0
        self._index.next_objnum = 0
        self._index.object_count = 0
        self._index.max_object = 0

        self._save_metadata()
        self._conn.commit()

        logger.info("New database created")

    def create_from_template(self, template_db: 'Database'):
        """
        Populate this database by copying every object from a template.

        Args:
            template_db (Database): An already-loaded database to copy from.
        """
        logger.info("Creating database from template...")

        # Create empty database structure
        self._create_new_database()

        # Copy all objects
        for obj in template_db.objects():
            new_obj = MOOObject.from_dict(obj.to_dict())
            new_obj._database = self
            self._admit(new_obj.objnum, new_obj)
            self._save_object_to_sql(new_obj)

        # Copy index
        self._index = DatabaseIndex.from_dict(template_db._index.to_dict())

        # Copy players
        self._players = template_db._players.copy()
        for name, objnum in self._players.items():
            self._conn.execute(
                "INSERT OR REPLACE INTO players (name, objnum) VALUES (?, ?)",
                (name, objnum)
            )

        # Copy recycled/reserved
        for objnum in self._index.recycled_objects:
            self._conn.execute(
                "INSERT OR IGNORE INTO recycled_objects (objnum) VALUES (?)",
                (objnum,)
            )
        for objnum in self._index.reserved_objects:
            self._conn.execute(
                "INSERT OR IGNORE INTO reserved_objects (objnum) VALUES (?)",
                (objnum,)
            )

        self._save_metadata()

        # Stamp which template this world was built from.
        #
        # Nothing else records it. `version` is the schema's, and `created`
        # is copied off the template, so it is identical in every world ever
        # made from it -- which means that until now a world could not say
        # what it started as.
        #
        # That is the whole difficulty in upgrading one. When a shipped
        # value differs from the template's, "the owner changed this" and
        # "this is simply the older default" look exactly the same, and they
        # want opposite treatment. Knowing the starting point makes it a
        # three-way comparison instead of a guess: unchanged from base takes
        # the new value, changed is the owner's and is left alone.
        #
        # The template ships inside the package, so the release version
        # names the template revision exactly. _save_metadata only replaces
        # its own six keys, so this survives every later save.
        from .globals import SERVER_VERSION
        self._conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            ('template_version', json.dumps(SERVER_VERSION))
        )

        self._conn.commit()

        logger.info(f"Created database with {self._index.object_count} objects "
                    f"from the {SERVER_VERSION} template")

    def _object_exists_in_sql(self, objnum: int) -> bool:
        """Check if an object exists in the SQLite database."""
        row = self._conn.execute(
            "SELECT 1 FROM objects WHERE objnum = ?", (objnum,)
        ).fetchone()
        return row is not None

    def _load_object_from_sql(self, objnum: int) -> MOOObject:
        """
        Load an object from SQLite and reconstruct a MOOObject.

        Args:
            objnum (int): Object number to load.

        Returns:
            MOOObject: The reconstructed object.

        Raises:
            KeyError: If the object does not exist.
        """
        # Load object row
        row = self._conn.execute(
            """SELECT objnum, parent, noun, aliases, owner,
                      location, flags, created, last_move
               FROM objects WHERE objnum = ?""",
            (objnum,)
        ).fetchone()

        if row is None:
            raise KeyError(f"Object #{objnum} not found")

        obj = MOOObject.__new__(MOOObject)
        # Initialize all the fields that __init__ would set
        obj.objnum = row[0]
        obj.parent = row[1]
        obj.noun = row[2]
        obj.aliases = json.loads(row[3])
        obj.owner = row[4]
        obj._location_id = row[5]
        obj.flags = row[6]
        obj.created = row[7]
        obj.last_move = row[8]

        # Initialize remaining MOOObject fields
        obj.properties = {}
        obj.verbs = []
        obj.children = set()
        obj._content_ids = []
        obj.tags = None  # Will be set below
        obj._resolved_properties = None
        obj._resolved_verbs = None
        obj._inheritance_cache_valid = False
        obj._cache_dirty = True
        obj._auto_save = True
        obj._database = None
        obj._pending_save = False
        # Straight off disk, so nothing is pending: the targeted write
        # path is eligible until something actually changes.
        obj._dirty_props = set()
        obj._all_dirty = False

        # Initialize tag handler
        from .objects import TagHandler
        obj.tags = TagHandler(obj)

        # Load properties
        prop_rows = self._conn.execute(
            "SELECT name, value, owner, perms FROM properties WHERE objnum = ?",
            (objnum,)
        ).fetchall()

        from .objects import PropertyInfo
        for name, value_json, prop_owner, perms in prop_rows:
            obj.properties[name] = PropertyInfo(
                name=name,
                value=json.loads(value_json) if value_json is not None else None,
                owner=prop_owner,
                perms=perms,
            )

        # Load verbs (ordered by position)
        verb_rows = self._conn.execute(
            """SELECT names, code, owner, perms, parent_type,
                      min_lengths, hidden, auth
               FROM verbs WHERE objnum = ? ORDER BY position""",
            (objnum,)
        ).fetchall()

        from .verbs import VerbDef
        for names_json, code, verb_owner, perms, parent_type, \
                min_lengths_json, hidden, auth in verb_rows:
            obj.verbs.append(VerbDef(
                names=json.loads(names_json),
                code=code,
                owner=verb_owner,
                perms=perms,
                parent_type=parent_type,
                min_lengths=json.loads(min_lengths_json),
                hidden=hidden,
                auth=auth,
            ))

        # Derive children from parent column
        child_rows = self._conn.execute(
            "SELECT objnum FROM objects WHERE parent = ?", (objnum,)
        ).fetchall()
        obj.children = {r[0] for r in child_rows}

        # Derive contents from location column (ordered by arrival time)
        content_rows = self._conn.execute(
            "SELECT objnum FROM objects WHERE location = ? AND objnum != ? ORDER BY last_move ASC",
            (objnum, objnum)
        ).fetchall()
        obj._content_ids = [r[0] for r in content_rows]

        return obj

    def _save_object_to_sql(self, obj: MOOObject):
        """
        Write an object to SQLite (INSERT OR REPLACE).

        Replaces the object row, all properties, and all verbs
        in a single transaction.

        Args:
            obj (MOOObject): The object to persist.
        """
        objnum = obj.objnum

        # A real upsert, not INSERT OR REPLACE.
        #
        # REPLACE is a DELETE followed by an INSERT, and `properties` and
        # `verbs` both carry ON DELETE CASCADE -- so writing the object
        # row destroyed every property and verb it had, every time.  The
        # full rewrite below hid it by re-inserting them immediately
        # afterwards, which is why saving one property had to write all
        # 192 rows: the DELETE was not thrift, it was repair.
        #
        # Updating in place cascades nothing, so a targeted write is
        # possible at all -- and the window where a concurrent reader
        # could see an object with no verbs is gone with it.
        self._conn.execute(
            """INSERT INTO objects
               (objnum, parent, noun, aliases, owner, location, flags,
                created, last_move)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(objnum) DO UPDATE SET
                   parent    = excluded.parent,
                   noun      = excluded.noun,
                   aliases   = excluded.aliases,
                   owner     = excluded.owner,
                   location  = excluded.location,
                   flags     = excluded.flags,
                   created   = excluded.created,
                   last_move = excluded.last_move""",
            (
                objnum,
                obj.parent,
                obj.noun,
                json.dumps(obj.aliases),
                obj.owner,
                obj._location_id,
                obj.flags,
                obj.created,
                obj.last_move,
            )
        )

        # The targeted path: only the properties whose values changed,
        # and no verb traffic at all.
        #
        # A full rewrite of a character prototype is 192 statements -- 111
        # properties and 78 verbs, the verbs carrying their entire source
        # text -- and it ran on *every* attribute assignment.  An object
        # is only eligible when nothing structural has happened to it;
        # _mark_modified sets _all_dirty for everything else, so a save
        # this code did not anticipate still writes the lot.
        if not getattr(obj, '_all_dirty', True):
            for name in getattr(obj, '_dirty_props', ()):
                prop = obj.properties.get(name)
                if prop is None:
                    self._conn.execute(
                        "DELETE FROM properties WHERE objnum = ? AND name = ?",
                        (objnum, name)
                    )
                    continue
                self._conn.execute(
                    """INSERT INTO properties (objnum, name, value, owner, perms)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(objnum, name) DO UPDATE SET
                           value = excluded.value,
                           owner = excluded.owner,
                           perms = excluded.perms""",
                    (objnum, name, json.dumps(prop.value), prop.owner, prop.perms)
                )
            obj.__dict__['_dirty_props'] = set()
            return

        # Replace all properties
        self._conn.execute(
            "DELETE FROM properties WHERE objnum = ?", (objnum,)
        )
        for name, prop in obj.properties.items():
            self._conn.execute(
                """INSERT INTO properties (objnum, name, value, owner, perms)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    objnum,
                    name,
                    json.dumps(prop.value),
                    prop.owner,
                    prop.perms,
                )
            )

        # Replace all verbs
        self._conn.execute(
            "DELETE FROM verbs WHERE objnum = ?", (objnum,)
        )
        for position, verb in enumerate(obj.verbs):
            self._conn.execute(
                """INSERT INTO verbs
                   (objnum, position, names, code, owner, perms,
                    parent_type, min_lengths, hidden, auth)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    objnum,
                    position,
                    json.dumps(verb.names),
                    verb.code,
                    verb.owner,
                    verb.perms,
                    verb.parent_type,
                    json.dumps(verb.min_lengths),
                    int(verb.hidden) if verb.hidden else 0,
                    verb.auth,
                )
            )

        # Everything on disk matches the object now, so the next save is
        # eligible for the targeted path until something dirties it again.
        obj.__dict__['_all_dirty'] = False
        obj.__dict__['_dirty_props'] = set()

    def _load_objects(self):
        """
        Preload objects into the in-memory cache at startup.

        Loads up to ``_cache_size`` objects in ascending objnum order.
        """
        rows = self._conn.execute(
            "SELECT objnum FROM objects ORDER BY objnum LIMIT ?",
            (self._cache_size,)
        ).fetchall()

        count = 0
        for (objnum,) in rows:
            if objnum not in self._index.recycled_objects:
                try:
                    obj = self._load_object_from_sql(objnum)
                    obj._database = self
                    obj.enable_auto_save(self)
                    self._admit(objnum, obj)
                    count += 1
                except Exception as e:
                    logger.error(f"Error loading object #{objnum}: {e}")

    def _load_metadata(self):
        """Load metadata from the ``metadata`` table."""
        data = {}
        rows = self._conn.execute(
            "SELECT key, value FROM metadata"
        ).fetchall()
        for key, value_json in rows:
            data[key] = json.loads(value_json)

        self._index.next_objnum = data.get('next_objnum', 1)
        self._index.object_count = data.get('object_count', 0)
        self._index.max_object = data.get('max_object', 0)
        self._index.created = data.get('created', time.time())
        self._index.last_checkpoint = data.get('last_checkpoint', time.time())
        self._index.version = data.get('version', '2.0')

    def _save_metadata(self):
        """Write metadata fields to the ``metadata`` table."""
        meta = {
            'next_objnum': self._index.next_objnum,
            'object_count': self._index.object_count,
            'max_object': self._index.max_object,
            'created': self._index.created,
            'last_checkpoint': self._index.last_checkpoint,
            'version': self._index.version,
        }
        for key, value in meta.items():
            self._conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                (key, json.dumps(value))
            )

    def template_version(self) -> Optional[str]:
        """
        The release whose template this world was built from, or None.

        None means the world predates the stamp -- every world created
        before it existed, which is most of them. Such a world can still be
        upgraded additively (a new prototype lands in the reserved number
        range, a new verb or property is simply absent), but a *changed*
        value cannot be judged: without the starting point there is no way
        to tell the owner's edit from the older default.

        Returns:
            str or None: e.g. ``'0.10.0-beta13'``.
        """
        row = self._conn.execute(
            "SELECT value FROM metadata WHERE key = 'template_version'"
        ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except (ValueError, TypeError):
            return row[0]

    def _load_recycled_reserved(self):
        """Load recycled and reserved sets from their tables."""
        rows = self._conn.execute(
            "SELECT objnum FROM recycled_objects"
        ).fetchall()
        self._index.recycled_objects = {r[0] for r in rows}

        rows = self._conn.execute(
            "SELECT objnum FROM reserved_objects"
        ).fetchall()
        self._index.reserved_objects = {r[0] for r in rows}

    def _load_players(self):
        """Load the player-name index from the ``players`` table."""
        rows = self._conn.execute(
            "SELECT name, objnum FROM players"
        ).fetchall()
        self._players = {name: objnum for name, objnum in rows}

    @contextmanager
    def transaction(self):
        """
        Context manager for grouping multiple operations into a single
        logical transaction.

        Acquires the database lock for the duration of the block.  On
        successful completion the changes are committed; if the block
        raises, they are rolled back.

        The rollback is the point.  Without it a failed block left its
        statements pending on the shared connection, and the next
        unrelated ``commit()`` -- a ticker saving itself, an autosave --
        wrote them out.  A transaction that raised could therefore still
        land, minutes later, in someone else's commit.

        Usage::

            with db.transaction():
                obj = db.create_object()
                obj.noun = "Test"
                db.save_object(obj)
        """
        with self._lock:
            try:
                yield
            except Exception:
                if self._conn:
                    self._conn.rollback()
                raise
            if self._conn:
                self._conn.commit()
