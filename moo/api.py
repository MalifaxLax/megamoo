"""
MegaMOO JSON API Server
========================

Provides a newline-delimited JSON-over-TCP API for external tools
(verb editors, admin dashboards, monitoring scripts, etc.) to interact
with the running MegaMOO server without connecting as a MUD client.

Protocol Overview
-----------------
The API uses a simple, text-based protocol that is easy to implement in
any language:

- **Transport**: Raw TCP (not HTTP).  Each message is a single JSON
  object followed by a newline (``\\n``).  This "JSON Lines" format
  allows messages to be read line-by-line.

- **Authentication**: If ``auth_token`` is configured (recommended),
  the first message from the client **must** be an ``auth`` command::

      {"cmd": "auth", "args": {"token": "my-secret-token"}}

  All subsequent commands are rejected until authentication succeeds.

- **Request format**::

      {"id": "req-1", "cmd": "command_name", "args": {...}}

  The ``id`` field is optional but recommended -- it is echoed back in
  the response so the client can match responses to requests.

- **Success response**::

      {"id": "req-1", "ok": true, "result": {...}}

- **Error response**::

      {"id": "req-1", "ok": false, "error": "Human-readable message"}

Available Commands
------------------
======================  =========================================================
Command                 Description
======================  =========================================================
``auth``                Authenticate with a token.
``get_object_info``     Retrieve summary info for an object (name, parent, etc.).
``list_verbs``          List verbs on an object (optionally including inherited).
``get_verb``            Get full verb details including source code.
``set_verb``            Create or update a verb's code and metadata.
``delete_verb``         Remove a verb from an object.
``list_properties``     List properties on an object (optionally inherited).
``get_property``        Get a property's value and metadata.
``eval``                Execute arbitrary verb code (admin/debugging tool).
``search_verbs``        Search verb source code by text or regex pattern.
``search_objects``      Search objects by name, noun, or alias.
``set_property``        Set (or add) a property value on an object.
``get_location``        Get an object's current location and its name.
``list_contents``       List the contents of an object/room as name-pairs.
``server_status``       Report server liveness, uptime, and player count.
``run_command``         Execute a game command as the TestBot character.
``disconnect_testbot``  Cleanly disconnect the TestBot session.
======================  =========================================================

Architecture Notes
------------------
* :class:`ApiServer` manages the TCP listener and connection lifecycle.
* :class:`ApiConnection` handles a single client: reading lines,
  dispatching commands, and sending responses.
* Command handlers are methods named ``_cmd_<command_name>`` on
  :class:`ApiConnection`.  Adding a new command is as simple as adding a
  new ``_cmd_*`` method.
* The API server runs in the same ``asyncio`` event loop as the main game
  server, so command handlers have direct access to the live database.

Security Considerations
-----------------------
* The API defaults to **localhost only** (``host='127.0.0.1'``) and
  **disabled** (``enabled=False``).
* Always set a strong ``auth_token`` when enabling the API.
* The ``eval`` command executes arbitrary code with full database access --
  treat it as a wizard-level operation.

See Also
--------
* ``config.py``  -- :class:`ApiConfig` for API server settings.
* ``verbs.py``   -- :class:`VerbDef` for verb data structures.
* ``builtins.py`` -- MOO builtins injected into the ``eval`` namespace.

Copyright (c) 2026
License: MIT
"""

import asyncio
import errno
import hmac
import json
import logging
import os
import re
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger('megamoo.api')


def _first_wizard(db):
    """
    Return the lowest-numbered wizard's object number, or ``None``.

    Used as the default identity for API eval.  Searching beats a constant
    because the wizard's number is a property of whichever database is
    loaded -- #100 in the shipped one, something else in a world that grew
    its own -- and the previous hard-coded default silently picked an exit.

    Args:
        db: The database to search.

    Returns:
        int | None: The object number, or ``None`` if there is no wizard.
    """
    from .objects import ObjectFlags

    # #0 carries the wizard flag in every database but is the system
    # object, not somebody who could have typed the command, so it is the
    # last resort rather than the first hit.  Nothing finer works across
    # databases: the PLAYER flag here means "connected right now", and
    # is_char is set on sf.db's wizard but not on the starter's.
    #
    # db.objects() yields in ascending objnum order, so the first wizard
    # that is not #0 is the lowest-numbered real one.
    fallback = None
    for obj in db.objects():
        if obj is None or not obj.has_flag(ObjectFlags.WIZARD):
            continue
        if obj.objnum != 0:
            return obj.objnum
        fallback = obj.objnum
    return fallback


# =============================================================================
# API CONNECTION HANDLER
# =============================================================================

class ApiConnection:
    """
    Handles a single API client TCP connection.

    Each connected client gets its own :class:`ApiConnection` instance that
    manages the read loop, authentication state, command dispatch, and
    response writing.

    The connection lifecycle is:

    1. Client connects -> ``handle()`` starts the read loop.
    2. Client sends ``{"cmd": "auth", ...}`` -> ``_cmd_auth()`` validates.
    3. Client sends commands -> ``dispatch()`` routes to ``_cmd_*`` handlers.
    4. Client disconnects (or connection drops) -> cleanup in ``handle()``'s
       ``finally`` block.

    Attributes:
        api (ApiServer):                 The parent server instance (provides
                                         access to ``database`` and ``config``).
        reader (asyncio.StreamReader):   Async stream for reading from the client.
        writer (asyncio.StreamWriter):   Async stream for writing to the client.
        authenticated (bool):            Whether this connection has successfully
                                         completed the ``auth`` handshake.
        peername (tuple):                The remote address ``(host, port)`` for
                                         logging.
    """

    def __init__(self, api: 'ApiServer', reader: Optional[asyncio.StreamReader],
                 writer: Optional[asyncio.StreamWriter]):
        """
        Initialise a new API connection.

        Args:
            api (ApiServer):                         The parent API server.
            reader (Optional[asyncio.StreamReader]):  The client's input stream.
                None is permitted for unit tests (no real socket).
            writer (Optional[asyncio.StreamWriter]):  The client's output stream.
                None is permitted for unit tests (no real socket).
        """
        self.api = api
        self.reader = reader
        self.writer = writer
        self.authenticated = False
        self.peername = writer.get_extra_info('peername') if writer else None

    # -------------------------------------------------------------------------
    # Connection lifecycle
    # -------------------------------------------------------------------------

    async def handle(self):
        """
        Main read loop for this connection.

        Reads lines from the client until the connection is closed (empty
        read) or an unrecoverable transport error occurs.  Each line is
        parsed as JSON and dispatched to the appropriate command handler.

        Parse errors result in an error response but do not close the
        connection -- the client can retry.  Command-handler exceptions
        are caught, logged, and returned as error responses.
        """
        logger.info(f"API connection from {self.peername}")
        try:
            while True:
                line = await self.reader.readline()
                if not line:
                    break  # Client disconnected
                try:
                    request = json.loads(line.decode('utf-8'))
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    await self._send({'ok': False, 'error': f'Invalid JSON: {e}'})
                    continue

                req_id = request.get('id')
                try:
                    result = await self.dispatch(request)
                    await self._send({'id': req_id, 'ok': True, 'result': result})
                except Exception as e:
                    logger.error(f"API command error: {e}", exc_info=True)
                    await self._send({'id': req_id, 'ok': False, 'error': str(e)})
        except (ConnectionResetError, BrokenPipeError):
            pass  # Client disconnected abruptly -- not an error
        finally:
            logger.info(f"API connection closed from {self.peername}")
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except Exception:
                pass

    async def dispatch(self, request: dict) -> dict:
        """
        Route a parsed request to the appropriate command handler.

        The ``cmd`` field in the request is used to find a method named
        ``_cmd_<cmd>`` on this instance.  The ``auth`` command is handled
        specially (it is allowed before authentication).

        Args:
            request (dict): The parsed JSON request.  Expected keys:
                - ``cmd`` (str): The command name.
                - ``args`` (dict, optional): Command arguments.

        Returns:
            dict: The result payload to include in the success response.

        Raises:
            PermissionError: If the client has not authenticated.
            ValueError: If the command name is unknown.
            Any exception raised by the command handler itself.
        """
        cmd = request.get('cmd', '')
        args = request.get('args', {})

        # Auth is the only command allowed before authentication
        if cmd == 'auth':
            return self._cmd_auth(args)

        if not self.authenticated:
            raise PermissionError('Not authenticated. Send {"cmd":"auth","args":{"token":"..."}} first.')

        # Look up handler method by naming convention: _cmd_<command_name>
        handler = getattr(self, f'_cmd_{cmd}', None)
        if handler is None:
            raise ValueError(f'Unknown command: {cmd}')

        result = handler(args)
        if asyncio.iscoroutine(result):
            result = await result
        return result

    async def _send(self, data: dict):
        """
        Send a JSON response line to the client.

        Serialises *data* as JSON (using ``str`` as a fallback for
        non-serialisable types), appends a newline, encodes as UTF-8,
        and flushes the write buffer.

        Args:
            data (dict): The response payload.
        """
        line = json.dumps(data, default=str) + '\n'
        self.writer.write(line.encode('utf-8'))
        await self.writer.drain()

    # =========================================================================
    # COMMAND HANDLERS
    # =========================================================================

    # ---- Authentication -----------------------------------------------------

    def _cmd_auth(self, args: dict) -> dict:
        """
        Authenticate the client with a shared-secret token.

        A server with no ``auth_token`` configured refuses to authenticate
        anyone.  It used to succeed unconditionally, which meant a plain
        ``--api`` with no token handed ``eval`` -- arbitrary Python, in
        process -- to anything that could reach the port.  Failing closed
        turns that from a silent hole into a startup message.

        Args:
            args (dict): Expected keys:
                - ``token`` (str): The authentication token.

        Returns:
            dict: ``{'authenticated': True}`` on success.

        Raises:
            PermissionError: If no token is configured, or if the supplied
                token does not match.
        """
        token = args.get('token', '')
        required = self.api.config.auth_token
        if not required:
            raise PermissionError(
                'API authentication is not configured, so no client can '
                'authenticate. Start the server with --api-token, or with '
                '--dev, which generates one.')
        # Constant time: a plain != leaks the token a byte at a time to
        # anyone who can measure the reply.
        if not hmac.compare_digest(str(token), str(required)):
            raise PermissionError('Invalid auth token')
        self.authenticated = True
        return {'authenticated': True}

    # ---- Object inspection --------------------------------------------------

    def _cmd_get_object_info(self, args: dict) -> dict:
        """
        Retrieve summary information about a single object.

        Args:
            args (dict): Expected keys:
                - ``objnum`` (int|str): The object number to look up.

        Returns:
            dict: Object metadata including ``objnum``, ``name``, ``noun``,
            ``aliases``, ``parent``, ``children``, ``location``, ``contents``,
            ``owner``, ``flags``, ``verb_count``, and ``property_count``.

        Raises:
            KeyError: If the object does not exist in the database.
        """
        objnum = int(args['objnum'])
        obj = self.api.database.get_object(objnum)
        return {
            'objnum': obj.objnum,
            'name': obj.name,
            'noun': obj.noun,
            'aliases': obj.aliases,
            'parent': obj.parent,
            'children': sorted(obj.children),
            'location': obj._location_id,
            'contents': sorted(obj._content_ids),
            'owner': obj.owner,
            'flags': obj.flags,
            'verb_count': len(obj.verbs),
            'property_count': len(obj.properties),
        }

    # ---- Verb operations ----------------------------------------------------

    def _cmd_list_verbs(self, args: dict) -> dict:
        """
        List verbs defined on an object.

        When ``inherited`` is ``True``, also walks the parent chain and
        includes inherited verbs (excluding those shadowed by local verbs
        with the same name set).

        Args:
            args (dict): Expected keys:
                - ``objnum`` (int|str): The object number.
                - ``inherited`` (bool, optional): Include inherited verbs.
                  Defaults to ``False``.

        Returns:
            dict: ``{'verbs': [...]}``, where each verb entry contains
            ``names``, ``owner``, ``perms``, ``parent_type``, and
            ``defined_on`` (the objnum where the verb is actually defined).
        """
        objnum = int(args['objnum'])
        inherited = args.get('inherited', False)
        obj = self.api.database.get_object(objnum)

        verbs = []
        # Local verbs defined directly on this object
        for v in obj.verbs:
            verbs.append({
                'names': v.names,
                'owner': v.owner,
                'perms': v.perms,
                'parent_type': v.parent_type,
                'defined_on': objnum,
            })

        # Walk the parent chain for inherited verbs if requested
        if inherited:
            # Track which verb name-sets we've already seen to avoid
            # showing shadowed (overridden) verbs
            seen_names = {tuple(v.names) for v in obj.verbs}
            current = obj.parent
            while current and current > 0:
                try:
                    parent_obj = self.api.database.get_object(current)
                except KeyError:
                    break
                for v in parent_obj.verbs:
                    key = tuple(v.names)
                    if key not in seen_names:
                        seen_names.add(key)
                        verbs.append({
                            'names': v.names,
                            'owner': v.owner,
                            'perms': v.perms,
                            'parent_type': v.parent_type,
                            'defined_on': current,
                        })
                current = parent_obj.parent

        return {'verbs': verbs}

    def _cmd_get_verb(self, args: dict) -> dict:
        """
        Get full details of a verb, including its source code.

        Searches the object's local verbs first, then walks up the parent
        chain to find inherited verbs.

        Args:
            args (dict): Expected keys:
                - ``objnum`` (int|str): The object number to start from.
                - ``verb_name`` (str): Name of the verb to retrieve.

        Returns:
            dict: Verb details including ``names``, ``code``, ``owner``,
            ``perms``, ``parent_type``, ``min_lengths``, and ``defined_on``.

        Raises:
            KeyError: If the verb is not found on the object or any ancestor.
        """
        objnum = int(args['objnum'])
        verb_name = args['verb_name']
        obj = self.api.database.get_object(objnum)

        # Search local verbs first
        for v in obj.verbs:
            if verb_name in v.names:
                return {
                    'names': v.names,
                    'code': v.code,
                    'owner': v.owner,
                    'perms': v.perms,
                    'parent_type': v.parent_type,
                    'min_lengths': v.min_lengths,
                    'defined_on': objnum,
                }

        # Walk up the parent chain to find inherited verbs
        current = obj.parent
        while current and current > 0:
            try:
                parent_obj = self.api.database.get_object(current)
            except KeyError:
                break
            for v in parent_obj.verbs:
                if verb_name in v.names:
                    return {
                        'names': v.names,
                        'code': v.code,
                        'owner': v.owner,
                        'perms': v.perms,
                        'parent_type': v.parent_type,
                        'min_lengths': v.min_lengths,
                        'defined_on': current,
                    }
            current = parent_obj.parent

        raise KeyError(f'Verb {verb_name!r} not found on #{objnum} or ancestors')

    def _cmd_set_verb(self, args: dict) -> dict:
        """
        Create or update a verb on an object.

        If a verb with the given name already exists on the object, it is
        updated in place.  Otherwise a new :class:`~moo.verbs.VerbDef` is
        created and appended to the object's verb list.

        After modification the verb is recompiled (``__post_init__``),
        the object's inheritance cache is invalidated, and the object is
        saved to disk.

        Args:
            args (dict): Expected keys:
                - ``objnum`` (int|str):    The object number.
                - ``verb_name`` (str):     Name to search for (update) or
                  default name (create).
                - ``code`` (str):          The verb source code.
                - ``names`` (list, optional): Verb name list (for create/rename).
                - ``owner`` (int, optional):  Verb owner objnum.
                - ``perms`` (str, optional):  Permission string (e.g. ``"rx"``).
                - ``parent_type`` (str, optional): Fully qualified verb type class.

        Returns:
            dict: ``{'saved': True, 'created': False}`` if updated, or
            ``{'saved': True, 'created': True}`` if newly created.
        """
        from .verbs import VerbDef

        objnum = int(args['objnum'])
        verb_name = args['verb_name']
        code = args['code']
        obj = self.api.database.get_object(objnum)

        # Search for an existing verb with this name
        for i, v in enumerate(obj.verbs):
            if verb_name in v.names:
                # Update existing verb in place
                v.code = code
                v.compiled_code = None  # Force recompilation
                if 'names' in args and args['names']:
                    v.names = args['names']
                if 'owner' in args:
                    v.owner = int(args['owner'])
                if 'perms' in args:
                    v.perms = args['perms']
                if 'parent_type' in args:
                    v.parent_type = args['parent_type']
                # Recompile the verb bytecode
                v.__post_init__()
                # _mark_modified, not just invalidate: a save only writes the
                # verbs table when the object is wholly dirty, and editing a
                # verb in place leaves nothing else to notice. Without this
                # the API answered {'saved': True} for a change that lived in
                # memory and died at the next restart.
                obj._mark_modified()
                self.api.database.save_object(obj)
                return {'saved': True, 'created': False}

        # No existing verb found -- create a new one
        new_verb = VerbDef(
            names=args.get('names', [verb_name]),
            code=code,
            owner=int(args.get('owner', 0)),
            perms=args.get('perms', 'rx'),
            parent_type=args.get('parent_type', 'moo.verb_types.MasterVerb'),
        )
        # add_verb rather than appending by hand: it invalidates the cache
        # *and* marks the object modified, which is what makes the save write
        # the verbs table at all.
        obj.add_verb(new_verb)
        self.api.database.save_object(obj)
        return {'saved': True, 'created': True}

    def _cmd_delete_verb(self, args: dict) -> dict:
        """
        Delete a verb from an object.

        Only removes the verb from the object's local verb list.  Inherited
        verbs (defined on parent objects) are not affected.

        Args:
            args (dict): Expected keys:
                - ``objnum`` (int|str): The object number.
                - ``verb_name`` (str):  Name of the verb to delete.

        Returns:
            dict: ``{'deleted': True}`` on success.

        Raises:
            KeyError: If no local verb with the given name exists.
        """
        objnum = int(args['objnum'])
        verb_name = args['verb_name']
        obj = self.api.database.get_object(objnum)

        # delete_verb rather than popping the list by hand: it marks the
        # object modified, and a save that is not told the object changed
        # structurally writes no verb rows -- so the deletion stayed in
        # memory and the verb came back at the next restart. It raises
        # KeyError on a missing name, which is this command's contract.
        obj.delete_verb(verb_name)
        self.api.database.save_object(obj)
        return {'deleted': True}

    # ---- Property operations ------------------------------------------------

    def _cmd_list_properties(self, args: dict) -> dict:
        """
        List properties defined on an object.

        When ``inherited`` is ``True``, also walks the parent chain and
        includes inherited properties (excluding those shadowed by local
        properties with the same name).

        Args:
            args (dict): Expected keys:
                - ``objnum`` (int|str): The object number.
                - ``inherited`` (bool, optional): Include inherited properties.
                  Defaults to ``False``.

        Returns:
            dict: ``{'properties': [...]}``, where each entry contains
            ``name``, ``owner``, ``perms``, ``type`` (Python type name of
            the value), and ``defined_on``.
        """
        objnum = int(args['objnum'])
        inherited = args.get('inherited', False)
        obj = self.api.database.get_object(objnum)

        props = []
        # Local properties
        for name, prop in obj.properties.items():
            props.append({
                'name': name,
                'owner': prop.owner,
                'perms': prop.perms,
                'type': type(prop.value).__name__,
                'defined_on': objnum,
            })

        # Walk parent chain for inherited properties if requested
        if inherited:
            seen = set(obj.properties.keys())
            current = obj.parent
            while current and current > 0:
                try:
                    parent_obj = self.api.database.get_object(current)
                except KeyError:
                    break
                for name, prop in parent_obj.properties.items():
                    if name not in seen:
                        seen.add(name)
                        props.append({
                            'name': name,
                            'owner': prop.owner,
                            'perms': prop.perms,
                            'type': type(prop.value).__name__,
                            'defined_on': current,
                        })
                current = parent_obj.parent

        return {'properties': props}

    def _cmd_get_property(self, args: dict) -> dict:
        """
        Get a property's value and metadata.

        Checks the object's local properties first, then walks up the
        parent chain to find inherited properties.

        Args:
            args (dict): Expected keys:
                - ``objnum`` (int|str): The object number.
                - ``name`` (str):       The property name.

        Returns:
            dict: Property details including ``name``, ``value``, ``owner``,
            ``perms``, and ``defined_on``.

        Raises:
            KeyError: If the property is not found on the object or ancestors.
        """
        objnum = int(args['objnum'])
        name = args['name']
        obj = self.api.database.get_object(objnum)

        # Check local properties first
        if name in obj.properties:
            prop = obj.properties[name]
            return {
                'name': name,
                'value': prop.value,
                'owner': prop.owner,
                'perms': prop.perms,
                'defined_on': objnum,
            }

        # Walk parent chain for inherited properties
        current = obj.parent
        while current and current > 0:
            try:
                parent_obj = self.api.database.get_object(current)
            except KeyError:
                break
            if name in parent_obj.properties:
                prop = parent_obj.properties[name]
                return {
                    'name': name,
                    'value': prop.value,
                    'owner': prop.owner,
                    'perms': prop.perms,
                    'defined_on': current,
                }
            current = parent_obj.parent

        raise KeyError(f'Property {name!r} not found on #{objnum} or ancestors')

    # ---- Code evaluation ----------------------------------------------------

    def _cmd_eval(self, args: dict) -> dict:
        """
        Execute arbitrary verb code and return the result.

        Builds a namespace that mirrors the verb execution environment
        (player, this, location, all MOO builtins, common Python builtins)
        and ``exec()``s the provided code within it.  Standard output is
        captured and returned alongside the value of the ``result`` variable
        (if set by the code).

        This is a **wizard-level** command intended for debugging and
        administration.

        Args:
            args (dict): Expected keys:
                - ``code`` (str):               The code to execute.
                - ``player_objnum`` (int, optional): Player context.
                  Defaults to the lowest-numbered wizard in the database.

        Returns:
            dict: ``{'value': repr_of_result, 'output': captured_stdout}``.

        Raises:
            Any exception raised by the executed code.
        """
        code = args['code']

        from .verbs import preprocess_verb_code
        from .verb_context import set_verb_context, clear_verb_context
        from . import builtins as moo_builtins

        db = self.api.database

        given = args.get('player_objnum')
        if given is None:
            # This used to default to #7, described as "the initial Admin
            # player".  In the shipped database #7 is a silver arch -- the
            # chargen exit -- which is neither a player nor a wizard, so
            # every unqualified eval ran with an exit's permissions and
            # could not so much as create a property.  Find a real wizard
            # instead: the number varies by database (#100 in mm.db), so
            # there is nothing safe to hard-code.
            player_objnum = _first_wizard(db)
            if player_objnum is None:
                raise ValueError(
                    "no wizard in this database to run eval as; "
                    "pass player_objnum explicitly")
        else:
            player_objnum = int(given)

        player = db.get_object(player_objnum)

        # Build the execution namespace to mirror verb context
        namespace = {
            'pobj': player,
            'player': player,
            'this': player,
            'location': player.location,
            'db': db,
            'args': '',
            'argstr': '',
        }

        # Inject all public MOO builtins (functions, constants, types)
        for name in dir(moo_builtins):
            if not name.startswith('_'):
                attr = getattr(moo_builtins, name)
                if callable(attr) or isinstance(attr, (str, int, type)):
                    namespace[name] = attr

        # Wire up search/find/call_verb with the correct database context
        namespace['call_verb'] = moo_builtins.make_call_verb(player, db)
        namespace['search'] = lambda *a, _db=db, **kw: moo_builtins._search_fn(*a, db=_db, **kw)
        namespace['find'] = lambda *a, _db=db, **kw: moo_builtins._find_fn(*a, db=_db, **kw)

        # Provide essential Python builtins (the exec namespace does not
        # inherit builtins automatically when a custom globals dict is used)
        namespace.update({
            'len': len, 'str': str, 'int': int, 'float': float, 'bool': bool,
            'list': list, 'dict': dict, 'set': set, 'tuple': tuple,
            'range': range, 'enumerate': enumerate, 'zip': zip,
            'print': print, 'sorted': sorted, 'sum': sum, 'min': min, 'max': max,
            'isinstance': isinstance, 'hasattr': hasattr,
            'getattr': getattr, 'setattr': setattr, 'type': type,
        })

        # Capture stdout so print() output can be returned to the client
        captured = io.StringIO()
        processed_code = preprocess_verb_code(code)

        # Set up the verb execution context for builtins that depend on it
        token = set_verb_context(player, db, depth=0)
        try:
            with redirect_stdout(captured):
                exec(compile(processed_code, '<api-eval>', 'exec'), namespace)
        finally:
            clear_verb_context(token)

        return {
            'value': repr(namespace.get('result')),
            'output': captured.getvalue(),
        }

    # ---- Search operations --------------------------------------------------

    def _cmd_search_verbs(self, args: dict) -> dict:
        """
        Search verb source code across all objects in the database.

        Performs a line-by-line scan of every verb's code, looking for
        lines that match the given pattern.  Supports both plain
        substring matching and regular expressions.

        Args:
            args (dict): Expected keys:
                - ``pattern`` (str):            The search pattern.
                - ``regex`` (bool, optional):   If ``True``, interpret
                  *pattern* as a regular expression.  Defaults to ``False``
                  (case-insensitive substring match).
                - ``max_results`` (int, optional): Maximum matches to return.
                  Defaults to ``100``.

        Returns:
            dict: ``{'matches': [...], 'truncated': bool}``.  Each match
            contains ``objnum``, ``obj_name``, ``verb_name``, ``line``
            (line number), and ``text`` (the matching line, stripped).

        Raises:
            ValueError: If *regex* is ``True`` and *pattern* is not a valid
            regular expression.
        """
        pattern = args['pattern']
        use_regex = args.get('regex', False)
        max_results = args.get('max_results', 100)

        # Build the match function (regex or plain substring)
        if use_regex:
            try:
                regex = re.compile(pattern, re.IGNORECASE)
            except re.error as e:
                raise ValueError(f'Invalid regex: {e}')
            match_fn = regex.search
        else:
            lower_pattern = pattern.lower()
            match_fn = lambda text: lower_pattern in text.lower()

        matches = []
        db = self.api.database
        for obj in db.objects():
            for verb in obj.verbs:
                if not verb.code:
                    continue
                for lineno, line in enumerate(verb.code.splitlines(), 1):
                    if match_fn(line):
                        matches.append({
                            'objnum': obj.objnum,
                            'obj_name': obj.name,
                            'verb_name': verb.names[0] if verb.names else '?',
                            'line': lineno,
                            'text': line.strip(),
                        })
                        if len(matches) >= max_results:
                            return {'matches': matches, 'truncated': True}

        return {'matches': matches, 'truncated': False}

    def _cmd_search_objects(self, args: dict) -> dict:
        """
        Search for objects by name, noun, or alias.

        A lightweight search for the API.  Supports ``#N`` dbref lookups
        and case-insensitive substring matching against object names,
        nouns, and aliases.

        Args:
            args (dict): Expected keys:
                - ``query`` (str):              The search string.
                - ``max_results`` (int, optional): Maximum matches to return.
                  Defaults to ``50``.

        Returns:
            dict: ``{'objects': [...]}``, where each entry contains
            ``objnum``, ``name``, ``noun``, ``parent``, and ``location``.
        """
        query = args['query'].lower()
        max_results = args.get('max_results', 50)

        # Try direct dbref lookup first (e.g. "#123")
        if query.startswith('#'):
            try:
                objnum = int(query[1:])
                obj = self.api.database.get_object(objnum)
                return {'objects': [{
                    'objnum': obj.objnum,
                    'name': obj.name,
                    'noun': obj.noun,
                    'parent': obj.parent,
                    'location': obj._location_id,
                }]}
            except (ValueError, KeyError):
                pass

        # Substring match across name, noun, and aliases
        matches = []
        for obj in self.api.database.objects():
            if (query in obj.name.lower() or
                    query in obj.noun.lower() or
                    any(query in a.lower() for a in obj.aliases)):
                matches.append({
                    'objnum': obj.objnum,
                    'name': obj.name,
                    'noun': obj.noun,
                    'parent': obj.parent,
                    'location': obj._location_id,
                })
                if len(matches) >= max_results:
                    break

        return {'objects': matches}

    # ---- Live-state commands (MCP support) ----------------------------------

    def _resolve_refs(self, value):
        """Resolve ``'#N'`` object-reference strings to live objects, recursively.

        Lets API / MCP callers pass object references the same way ``#N`` works
        in verb code and ``@set``: a top-level or nested ``'#N'`` string becomes
        the live object, which the property serialiser then stores canonically
        (a ``'#N'`` string for a scalar, a bare int objnum inside a list/dict).
        A reference to a missing object raises, surfaced to the caller as an
        error rather than silently stored as broken text.

        Args:
            value: The incoming JSON value, possibly containing ``'#N'`` refs.

        Returns:
            The value with every ``'#N'`` reference string replaced by its
            live MOOObject.
        """
        if (isinstance(value, str) and len(value) > 1
                and value[0] == '#' and value[1:].isdigit()):
            return self.api.database.get_object(int(value[1:]))
        if isinstance(value, list):
            return [self._resolve_refs(v) for v in value]
        if isinstance(value, dict):
            return {k: self._resolve_refs(v) for k, v in value.items()}
        return value

    def _cmd_set_property(self, args: dict) -> dict:
        """
        Set a property value on an object (added if not yet defined).

        ``'#N'`` strings in the value are resolved to object references (see
        ``_resolve_refs``), so references may be passed uniformly as ``"#5"``.

        Args:
            args (dict): Expected keys:
                - ``objnum`` (int|str): The object number.
                - ``name`` (str): Property name.
                - ``value``: JSON-representable value; ``"#N"`` = object ref.

        Returns:
            dict: ``{'objnum': ..., 'name': ..., 'value': ...}`` where ``value``
            is the canonical stored form ('#N' scalars, int objnums in lists).
        """
        objnum = int(args['objnum'])
        name = args['name']
        value = self._resolve_refs(args['value'])
        obj = self.api.database.get_object(objnum)
        try:
            obj.set_property(name, value)
        except KeyError:
            obj.add_property(name, value)
        self.api.database.save_object(obj)
        # Report the serialised form actually stored (JSON-safe: never a live
        # object), so callers see '#N' / int objnums rather than object reprs.
        stored = obj.properties[name].value if name in obj.properties else value
        return {'objnum': objnum, 'name': name, 'value': stored}

    def _cmd_get_location(self, args: dict) -> dict:
        """
        Get an object's location and the location's name.

        Args:
            args (dict): Expected keys:
                - ``objnum`` (int|str): The object number.

        Returns:
            dict: ``{'objnum', 'location', 'location_name'}``;
            ``location_name`` is ``None`` if the object is nowhere.
        """
        obj = self.api.database.get_object(int(args['objnum']))
        loc = obj._location_id or None   # normalize "nowhere" (0) to None
        loc_name = None
        if loc and self.api.database.valid(loc):
            loc_name = self.api.database.get_object(loc).name
        return {'objnum': obj.objnum, 'location': loc,
                'location_name': loc_name}

    def _cmd_list_contents(self, args: dict) -> dict:
        """
        List the contents of an object/room as objnum + name pairs.

        Args:
            args (dict): Expected keys:
                - ``objnum`` (int|str): The container/room object number.

        Returns:
            dict: ``{'objnum': ..., 'contents': [{'objnum', 'name'}, ...]}``.
        """
        obj = self.api.database.get_object(int(args['objnum']))
        contents = []
        for c in obj._content_ids:   # preserve in-room order
            try:
                contents.append(
                    {'objnum': c,
                     'name': self.api.database.get_object(c).name})
            except KeyError:
                contents.append({'objnum': c, 'name': None})
        return {'objnum': obj.objnum, 'contents': contents}

    def _cmd_server_status(self, args: dict) -> dict:
        """
        Report server liveness, uptime, and connection count.

        ``api_port`` is the port the API actually bound, which with
        auto-selection need not be the configured one -- handy for
        confirming which server a client is talking to.

        Returns:
            dict: ``{'running', 'uptime_seconds', 'connected_players',
            'database', 'api_port'}``.

        Raises:
            RuntimeError: If the API server has no game-server reference.
        """
        server = self.api.server
        if server is None:
            raise RuntimeError(
                'API server has no game-server reference')
        uptime = (asyncio.get_event_loop().time()
                  - server.state.start_time)
        from .network import _player_connections
        return {'running': server.state.running,
                'uptime_seconds': round(uptime, 1),
                'connected_players': len(_player_connections),
                'database': str(getattr(self.api.database, 'path', '')),
                'api_port': self.api.port}

    async def _cmd_run_command(self, args: dict) -> dict:
        """
        Execute a game command as the TestBot character.

        Activates TestBot on a VirtualConnection on first use (the
        session persists across calls so location/combat state carries
        over).  Output captured between calls — e.g. roundtime echoes
        landing after a previous call's grace period — is intentionally
        included at the start of this call's result rather than dropped.

        Args:
            args (dict): Expected keys:
                - ``command`` (str): The raw command, e.g. ``"look"``.
                - ``wait`` (float, optional): Grace period in seconds
                  after the command completes so ticker/roundtime
                  output lands.  Defaults to 1.0.

        Returns:
            dict: ``{'testbot': objnum, 'output': captured text}``.

        Raises:
            RuntimeError: If the API has no game-server reference.
        """
        command = str(args['command'])
        # Clamp: the grace period holds testbot_lock, so an oversized
        # wait would stall every queued run_command/disconnect call.
        wait = min(max(float(args.get('wait', 1.0)), 0.0), 30.0)
        server = self.api.server
        if server is None:
            raise RuntimeError('API server has no game-server reference')

        # Serialize: overlapping commands would make output attribution
        # ambiguous (single shared TestBot buffer).
        async with self.api.testbot_lock:
            conn = self.api.testbot_conn
            if conn is None:
                from .virtual_connection import (find_or_create_testbot,
                                                 activate_testbot)
                bot = find_or_create_testbot(
                    self.api.database, self.api.config.testbot_objnum)
                try:
                    conn = activate_testbot(server, bot)
                except Exception:
                    # Don't leave a half-registered connection behind.
                    from .network import _player_connections, _pc_lock
                    with _pc_lock:
                        _player_connections.pop(bot.objnum, None)
                    raise
                self.api.testbot_conn = conn

            await server.execute_command(conn.player_obj, command)
            await asyncio.sleep(wait)
            return {'testbot': conn.player_obj.objnum,
                    'output': conn.drain()}

    async def _cmd_disconnect_testbot(self, args: dict) -> dict:
        """
        Cleanly disconnect the TestBot session (normal unpuppet path).

        Returns:
            dict: ``{'disconnected': bool}`` — ``False`` if TestBot
            was not connected.
        """
        async with self.api.testbot_lock:
            conn = self.api.testbot_conn
            if conn is None:
                return {'disconnected': False}
            from .virtual_connection import deactivate_testbot
            deactivate_testbot(conn)
            self.api.testbot_conn = None
            return {'disconnected': True}


# =============================================================================
# API SERVER
# =============================================================================

class ApiServer:
    """
    TCP server that accepts API connections and manages their lifecycle.

    The :class:`ApiServer` is started and stopped by the main server
    process.  It runs within the same ``asyncio`` event loop, so there
    is no cross-thread synchronisation needed for database access.

    Attributes:
        database:       The live :class:`~moo.database.Database` instance.
        config:         The :class:`~moo.config.ApiConfig` with host, port,
                        and auth_token settings.
        port:           The port actually bound.  With ``config.auto_port``
                        this can differ from ``config.port`` -- read this,
                        never ``config.port``, when reporting the address.
        _server:        The underlying :class:`asyncio.AbstractServer` (set
                        after :meth:`start`).
        _connections:   List of active :class:`ApiConnection` instances.

    Usage::

        api = ApiServer(database, config.api)
        await api.start()   # Begin accepting connections
        # ... server runs ...
        await api.stop()    # Graceful shutdown
    """

    def __init__(self, database, config, server=None):
        """
        Initialise the API server.

        Args:
            database: The MegaMOO :class:`~moo.database.Database` instance.
            config:   An :class:`~moo.config.ApiConfig` dataclass instance.
            server:   The owning MegaMOOServer instance, or None (command
                      dispatch and status need it).
        """
        self.database = database
        self.config = config
        self.server = server
        self.port = config.port           # actual bound port; see start()
        self.testbot_conn = None          # VirtualConnection once activated
        self.testbot_lock = asyncio.Lock()  # serialize run_command calls
        self._server: Optional[asyncio.AbstractServer] = None
        self._connections: list[ApiConnection] = []

    async def start(self):
        """
        Start listening for API connections.

        Binds to the host in ``self.config`` and begins accepting new TCP
        connections; each is handled by :meth:`_handle_connection` in its
        own asyncio task.

        Port selection: ``config.port`` is tried first.  If it is already
        taken and ``config.auto_port`` is on (the default), the next
        ``config.port_scan_limit - 1`` ports are tried in turn, so a second
        database can be launched with ``--api`` without hand-picking a free
        port.  ``config.auto_port`` is off when the operator named a port
        explicitly (``--api-port``), in which case a busy port is a hard
        error rather than a silent move somewhere else.

        The port that actually won is recorded in ``self.port`` and
        published in the discovery file (see :meth:`_write_info_file`).

        Raises:
            OSError: If no candidate port could be bound.
        """
        first = self.config.port
        limit = self.config.port_scan_limit if self.config.auto_port else 1
        last_error = None

        for port in range(first, min(first + limit, 65536)):
            try:
                self._server = await asyncio.start_server(
                    self._handle_connection,
                    self.config.host,
                    port,
                )
            except OSError as e:
                # EADDRINUSE is the only condition worth walking past: any
                # other bind failure (bad host, permission denied) will
                # repeat identically on every port.
                if e.errno != errno.EADDRINUSE:
                    raise
                last_error = e
                continue

            self.port = port
            if port != first:
                logger.warning(
                    f"API port {first} in use; auto-selected {port}"
                )
            logger.info(f"API server listening on {self.config.host}:{port}")
            self._write_info_file()
            return

        # Fell off the end of the scan without binding anything.
        tried = (f"port {first}" if limit == 1
                 else f"ports {first}-{min(first + limit - 1, 65535)}")
        raise OSError(
            f"Could not start API server: {tried} already in use"
        ) from last_error

    # ---- Discovery file -----------------------------------------------------

    def _info_path(self) -> Optional[Path]:
        """
        Resolve the discovery-file path, or ``None`` if disabled.

        ``config.info_path`` wins when set; ``'-'`` disables the file.
        Otherwise it is derived from the database path so that each
        database advertises its own API (``sf.db`` -> ``sf.db.api.json``).
        """
        configured = (self.config.info_path or '').strip()
        if configured == '-':
            return None
        if configured:
            return Path(configured).expanduser()
        db_path = getattr(self.database, 'path', None)
        if not db_path:
            return None
        return Path(str(db_path) + '.api.json')

    def _write_info_file(self):
        """
        Publish where the API is listening, for local tooling to find.

        Written after a successful bind; holds the host/port actually in
        use plus our pid, which lets readers spot a file left behind by a
        crashed server.  Never fatal: an unwritable directory costs
        discovery, not the API itself.
        """
        path = self._info_path()
        if path is None:
            return
        db_path = str(getattr(self.database, 'path', ''))
        info = {
            'host': self.config.host,
            'port': self.port,
            'pid': os.getpid(),
            # Absolute: the path is read by tools with a different working
            # directory, and "sf.db" tells them nothing about which one.
            'database': str(Path(db_path).resolve()) if db_path else '',
            'auth_required': bool(self.config.auth_token),
        }
        # The telnet port the game itself bound -- also auto-selected, so
        # a tool listing running servers can say where to point a client.
        # The listener is up before the API starts, so this is the real
        # port, not the configured first candidate.
        game_port = getattr(self.server, 'port', None)
        if isinstance(game_port, int):
            info['game_port'] = game_port
        # The browser client's port, when one is served.  Auto-selected
        # like the others and worth recording for the same reason, only
        # more so: this is the address a person actually opens, and with
        # it missing the only ways to find a running world's client were
        # to read the startup log or guess.  Left absent rather than null
        # when --web is off, so a reader can tell "no client here" from
        # "client on a port I do not know".
        web_port = getattr(self.server, 'web_port', None)
        if isinstance(web_port, int):
            info['web_port'] = web_port
        try:
            path.write_text(json.dumps(info, indent=2) + '\n',
                            encoding='utf-8')
            logger.info(f"API discovery file written: {path}")
        except OSError as e:
            logger.warning(f"Could not write API discovery file {path}: {e}")

    def _remove_info_file(self):
        """Remove our discovery file, if it is still ours to remove."""
        path = self._info_path()
        if path is None:
            return
        try:
            # Only clean up a file describing *this* process: a restarted
            # server may already have replaced it with its own.
            info = json.loads(path.read_text(encoding='utf-8'))
            if info.get('pid') not in (None, os.getpid()):
                return
            path.unlink()
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            logger.warning(f"Could not remove API discovery file {path}: {e}")

    async def stop(self):
        """
        Stop the API server and close all active connections.

        Closes the listening socket first (preventing new connections),
        then forcibly closes each active client connection.
        """
        self._remove_info_file()

        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("API server stopped")

        # Close all active client connections
        for conn in list(self._connections):
            conn.writer.close()
            try:
                await conn.writer.wait_closed()
            except Exception:
                pass
        self._connections.clear()

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                 writer: asyncio.StreamWriter):
        """
        Callback for new TCP connections from ``asyncio.start_server``.

        Creates an :class:`ApiConnection`, registers it in ``_connections``,
        runs its :meth:`~ApiConnection.handle` loop, and removes it on
        completion.

        Args:
            reader (asyncio.StreamReader): The new client's input stream.
            writer (asyncio.StreamWriter): The new client's output stream.
        """
        conn = ApiConnection(self, reader, writer)
        self._connections.append(conn)
        try:
            await conn.handle()
        finally:
            if conn in self._connections:
                self._connections.remove(conn)
