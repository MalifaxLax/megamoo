"""
MegaMOO TickerHandler -- Periodic Verb Callback System

A periodic callback system inspired by Evennia's TickerHandler. Objects
subscribe with an interval and a verb name; the handler calls that verb
on the object at the specified interval, enabling heartbeats, regeneration
timers, weather cycles, NPC AI loops, and any other recurring behavior.

Overview
--------
The TickerHandler maintains a dictionary of **subscriptions**, each
identified by a composite key of ``(objnum, idstring)``. A subscription
records:

- **interval** -- how many seconds between fires.
- **verb** -- the verb name to call on the object each tick.
- **next_fire** -- the Unix timestamp when the next fire is due.

The handler's ``run()`` coroutine is launched as an ``asyncio.Task`` by
the server during startup. It wakes up every second, scans all
subscriptions, and fires any that are due.

Persistence
-----------
Subscription data is persisted to the ``tickers`` table in the SQLite
database.  On server restart, ``restore()`` reloads subscriptions from
that table.  Each object also gets a mirrored ``.tickers`` property so
that in-game code can inspect an object's active subscriptions.

Architecture
------------
::

    Verb code: ticker_add(30, 'at_regen', pobj, 'regen')
        |
        v
    TickerHandler.add(30, 'at_regen', pobj, 'regen')
        |
        +--> _subscriptions[(pobj.objnum, 'regen')] = {interval, verb, next_fire}
        +--> _update_obj_tickers(pobj)   -- mirrors to pobj.tickers
        +--> _save()                     -- persists to tickers table
        |
        v
    TickerHandler.run() loop (every 1 second):
        |
        +--> now >= sub['next_fire']?
        |        |
        |        +--> YES: _fire(objnum, verb) --> call_verb(obj, verb)
        |        |         sub['next_fire'] = now + interval
        |        +--> NO:  skip
        v

Thread Safety Note
------------------
The ``run()`` coroutine executes on the asyncio event loop but dispatches
``_fire()`` to the server's ``ThreadPoolExecutor`` via
``loop.run_in_executor()``, wrapped in ``asyncio.wait_for()`` to enforce
a wallclock timeout.  This ensures that a slow or runaway ticker verb
never blocks the event loop.  The ``add()``, ``remove()``, and
``remove_all()`` methods are called from verb code (on the worker
thread), so mutations to ``_subscriptions`` are effectively serialised.

Usage from verb code::

    ticker_add(30, 'at_regen', pobj, 'regen')   # fire at_regen every 30s
    ticker_remove(pobj, 'regen')                 # stop the regen ticker
    ticker_list(pobj)                            # list pobj's tickers

See Also
--------
- ``server.py`` -- creates the TickerHandler and launches ``run()``.
- ``builtins.py`` -- provides ``ticker_add()``, ``ticker_remove()``,
  ``ticker_list()`` wrappers that delegate to this module.
- ``effects.py`` -- the effects system uses a 1-second ticker
  subscription (``'effect_dispatcher'``) to drive timed effects.
- ``verb_context.py`` -- ``_fire()`` sets up a verb context so the
  called verb has access to the database and a valid pobj.

Copyright (c) 2026
License: MIT
"""

# =============================================================================
# IMPORTS
# =============================================================================

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from .database import Database
    from .objects import MOOObject
    from .server import MegaMOOServer

logger = logging.getLogger(__name__)


# =============================================================================
# TICKER HANDLER
# =============================================================================


class TickerHandler:
    """
    Manages periodic verb callbacks on MOO objects.

    Each subscription is keyed by ``(objnum, idstring)`` where
    ``idstring`` is a caller-chosen label that allows multiple
    independent tickers on the same object (e.g. ``'regen'``,
    ``'poison'``, ``'weather'``). Duplicate subscriptions (same
    objnum + idstring) overwrite the previous entry.

    Attributes:
        _subscriptions (Dict[Tuple[int, str], dict]): Active ticker
            subscriptions. Keys are ``(objnum, idstring)`` tuples.
            Values are dicts with ``'interval'``, ``'verb'``, and
            ``'next_fire'`` keys.
        _db (Optional[Database]): Reference to the game database.
    """

    def __init__(self, db: Database):
        """
        Initialize the TickerHandler.

        Args:
            db: The game database (provides SQLite connection for
                ticker persistence).
        """
        # Key: (objnum, idstring), Value: subscription dict
        self._subscriptions: Dict[Tuple[int, str], dict] = {}
        self._db: Optional[Database] = db

    # -----------------------------------------------------------------
    # Startup / Restore
    # -----------------------------------------------------------------

    def restore(self, db: Database):
        """
        Restore ticker subscriptions from the ``tickers`` table.

        Reads the persisted rows and rebuilds the in-memory subscription
        dictionary. Each subscription's ``next_fire`` is recalculated
        relative to the current time.

        Args:
            db: The game database.
        """
        self._db = db
        if not db._conn:
            return
        try:
            rows = db._conn.execute(
                "SELECT objnum, idstring, interval, verb_name FROM tickers"
            ).fetchall()
            now = time.time()
            for objnum, idstring, interval, verb_name in rows:
                self._subscriptions[(objnum, idstring)] = {
                    'interval': interval,
                    'verb': verb_name,
                    'next_fire': now + interval,
                }
            logger.info(f"TickerHandler restored {len(self._subscriptions)} subscriptions")
        except Exception as e:
            logger.error(f"TickerHandler restore failed: {e}")

    # -----------------------------------------------------------------
    # Subscription management
    # -----------------------------------------------------------------

    def add(self, interval: float, verb_name: str, obj: Any, idstring: str = ''):
        """
        Subscribe an object to periodic verb calls.

        If a subscription with the same ``(objnum, idstring)`` already
        exists, it is silently replaced with the new parameters.

        Args:
            interval: Seconds between verb calls.
            verb_name: Name of the verb to call each tick.
            obj: The MOOObject to subscribe, or its object number.
            idstring: Label for this subscription. Defaults to ``''``.
        """
        from .objects import MOOObject
        if isinstance(obj, int):
            obj = self._db.get_object(obj)
        objnum = obj.objnum

        self._subscriptions[(objnum, idstring)] = {
            'interval': interval,
            'verb': verb_name,
            'next_fire': time.time() + interval,
        }
        self._update_obj_tickers(obj)
        self._save_ticker(objnum, idstring, interval, verb_name)
        logger.debug(f"Ticker added: #{objnum} '{idstring}' every {interval}s -> {verb_name}")

    def remove(self, obj: Any, idstring: str = ''):
        """
        Unsubscribe an object from a specific ticker.

        Args:
            obj: The MOOObject to unsubscribe, or its object number.
            idstring: The label identifying which subscription to remove.
        """
        from .objects import MOOObject
        if isinstance(obj, int):
            obj = self._db.get_object(obj)
        objnum = obj.objnum

        key = (objnum, idstring)
        if key in self._subscriptions:
            del self._subscriptions[key]
            self._update_obj_tickers(obj)
            self._delete_ticker(objnum, idstring)
            logger.debug(f"Ticker removed: #{objnum} '{idstring}'")

    def remove_all(self, obj: Any):
        """
        Remove all ticker subscriptions for an object.

        Args:
            obj: The MOOObject whose tickers should be cleared.
        """
        from .objects import MOOObject
        if isinstance(obj, int):
            obj = self._db.get_object(obj)
        objnum = obj.objnum

        keys = [k for k in self._subscriptions if k[0] == objnum]
        for key in keys:
            del self._subscriptions[key]
        self._update_obj_tickers(obj)
        self._delete_all_tickers(objnum)
        if keys:
            logger.debug(f"All tickers removed for #{objnum} ({len(keys)} removed)")

    # -----------------------------------------------------------------
    # Query / List
    # -----------------------------------------------------------------

    def all(self, obj: Any = None) -> List[dict]:
        """
        List ticker subscriptions, optionally filtered by object.

        Args:
            obj: If provided, only return subscriptions for this object.

        Returns:
            List[dict]: Subscription info dicts.
        """
        result = []
        for (objnum, idstring), sub in self._subscriptions.items():
            if obj is not None:
                from .objects import MOOObject
                check_num = obj.objnum if isinstance(obj, MOOObject) else int(obj)
                if objnum != check_num:
                    continue
            result.append({
                'objnum': objnum,
                'id': idstring,
                'interval': sub['interval'],
                'verb': sub['verb'],
            })
        return result

    # -----------------------------------------------------------------
    # Main loop -- runs as an asyncio background task
    # -----------------------------------------------------------------

    async def run(self, server: MegaMOOServer):
        """
        Background coroutine that fires due subscriptions every second.

        Due tickers are launched as fire-and-forget ``asyncio.Task``\\s
        that dispatch to the server's verb thread pool.  The run loop
        never awaits verb execution, so a slow or runaway ticker can
        never block the event loop or delay other tickers.

        Args:
            server: The MegaMOOServer instance.
        """
        self._db = server.database
        self._server = server
        while server.state.running:
            await asyncio.sleep(1)
            if not server.state.running:
                break
            now = time.time()
            for key, sub in list(self._subscriptions.items()):
                if now >= sub['next_fire']:
                    sub['next_fire'] = now + sub['interval']
                    objnum, idstring = key
                    asyncio.create_task(
                        self._fire_async(objnum, idstring, sub['verb']))

    async def _fire_async(self, objnum: int, idstring: str, verb: str):
        """Dispatch a single ticker verb to the thread pool with timeout."""
        from .globals import COMMAND_TIMEOUT

        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(
                    self._server._verb_thread_pool,
                    self._fire, objnum, verb),
                timeout=COMMAND_TIMEOUT)
        except asyncio.TimeoutError:
            logger.error(
                f"Ticker verb '{verb}' on #{objnum} timed out "
                f"after {COMMAND_TIMEOUT}s")
        except Exception as e:
            logger.error(f"Ticker fire error #{objnum} '{idstring}': {e}")

    # -----------------------------------------------------------------
    # Verb invocation
    # -----------------------------------------------------------------

    def _fire(self, objnum: int, verb_name: str):
        """
        Call a verb on an object as a ticker callback.

        Args:
            objnum: Object number to call the verb on.
            verb_name: Name of the verb to invoke.
        """
        from .verb_context import set_verb_context, clear_verb_context
        from .builtins import make_call_verb

        try:
            obj = self._db.get_object(objnum)
        except KeyError:
            keys = [k for k in self._subscriptions if k[0] == objnum]
            for key in keys:
                del self._subscriptions[key]
            if keys:
                self._delete_all_tickers(objnum)
                logger.info(f"Auto-removed {len(keys)} stale ticker(s) for deleted object #{objnum}")
            return
        if obj is None:
            return

        token = set_verb_context(obj, self._db, depth=0)
        try:
            call_verb = make_call_verb(obj, self._db, _depth=0)
            call_verb(obj, verb_name)
        except KeyError:
            pass
        except Exception as e:
            logger.error(f"Ticker verb {verb_name} on #{objnum} raised: {e}")
        finally:
            clear_verb_context(token)

    # -----------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------

    def _update_obj_tickers(self, obj: Any):
        """Mirror subscription data to the object's ``.tickers`` property."""
        from .objects import MOOObject
        if isinstance(obj, int):
            obj = self._db.get_object(obj)
        objnum = obj.objnum

        tickers = []
        for (on, ids), sub in self._subscriptions.items():
            if on == objnum:
                tickers.append({
                    'id': ids,
                    'interval': sub['interval'],
                    'verb': sub['verb'],
                })
        obj.tickers = tickers if tickers else None

    def _save_ticker(self, objnum: int, idstring: str,
                     interval: float, verb_name: str):
        """INSERT OR REPLACE a single ticker row."""
        try:
            self._db._conn.execute(
                """INSERT OR REPLACE INTO tickers
                   (objnum, idstring, interval, verb_name)
                   VALUES (?, ?, ?, ?)""",
                (objnum, idstring, interval, verb_name)
            )
            self._db._conn.commit()
        except Exception as e:
            logger.error(f"TickerHandler save failed: {e}")

    def _delete_ticker(self, objnum: int, idstring: str):
        """DELETE a single ticker row."""
        try:
            self._db._conn.execute(
                "DELETE FROM tickers WHERE objnum = ? AND idstring = ?",
                (objnum, idstring)
            )
            self._db._conn.commit()
        except Exception as e:
            logger.error(f"TickerHandler delete failed: {e}")

    def _delete_all_tickers(self, objnum: int):
        """DELETE all ticker rows for an object."""
        try:
            self._db._conn.execute(
                "DELETE FROM tickers WHERE objnum = ?", (objnum,)
            )
            self._db._conn.commit()
        except Exception as e:
            logger.error(f"TickerHandler delete-all failed: {e}")
