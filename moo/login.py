"""
MegaMOO Login Handler

Implements pre-authentication login, modeled after LambdaMOO's
``do_login_command`` verb on #0.

This module owns the entire login conversation between a new TCP
connection and the game engine.  It is deliberately decoupled from the
networking layer: ``LoginHandler.run()`` receives abstract ``send``
and ``read_line`` callables, making it testable without a live socket.

Architecture::

    PlayerConnection._handle_login()
      └─ LoginHandler.run(send, read_line)
           ├─ load_display_screen()     → ASCII splash banner
           ├─ username prompt loop      → up to *max_attempts* tries
           │    ├─ "NEW" → _create_flow()  → new account sub-flow
           │    └─ name  → password check  → return player object
           └─ returns MOOObject | None

The login flow is driven as a sequential async conversation:

    1. Display screen (ASCII art splash loaded from a text file).
    2. Prompt: "Enter your username or NEW to create a new account:"
    3a. Existing name -> "Password:" -> verify -> connect.
    3b. "NEW" -> create-account sub-flow.

Password storage:

    Passwords are hashed with **bcrypt** when available (preferred), or
    a salted SHA-256 fallback.  The fallback is intentionally simple —
    production deployments should ``pip install bcrypt``.  Empty hashes
    are treated as "no password set" and accept any input, which allows
    freshly-created pool objects to be claimed without a password
    migration step.

Player pool system:

    New accounts are *not* created from scratch.  Instead, the server
    pre-populates ``#2`` (PlayerObjectDB) with blank ``PlayerPlace``
    objects.  ``_create_flow()`` claims the first available one,
    renames it, sets a password, and returns it.  This avoids runtime
    object creation and keeps object numbering predictable.

Copyright (c) 2026
License: MIT
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .objects import MOOObject, ObjectFlags
from .globals import SERVER_VERSION
from .globals import PASSWORD_PROMPT_RE  # noqa: F401  (re-exported for callers)

if TYPE_CHECKING:
    from .database import Database
    from .config import ServerConfig

logger = logging.getLogger('megamoo.login')


# ---------------------------------------------------------------------------
#   Optional bcrypt dependency
# ---------------------------------------------------------------------------

# Try to import bcrypt; fall back to hashlib-based hashing.
# bcrypt is strongly preferred for production — SHA-256 is a
# convenience fallback for development environments without compiled
# C extensions.
try:
    import bcrypt as _bcrypt  # pip install bcrypt
    _HAS_BCRYPT = True
except ImportError:
    _bcrypt = None
    _HAS_BCRYPT = False


# =========================================================================
#   Password utilities
# =========================================================================

def hash_password(plain: str) -> str:
    """Hash a plaintext password for storage.

    Uses **bcrypt** when the library is installed (the recommended
    path), otherwise falls back to a salted SHA-256 scheme.  The
    fallback format is::

        $sha256$<32-char-hex-salt>$<64-char-hex-digest>

    This is *not* a standard format — it exists solely so the server
    can run without compiled dependencies during early development.

    Args:
        plain: The plaintext password to hash.

    Returns:
        A hashed password string suitable for persistent storage.
        The format depends on which hashing backend is available.
    """
    if _HAS_BCRYPT:
        return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()
    # Fallback: salted SHA-256
    salt = secrets.token_hex(16)
    digest = hashlib.sha256((salt + plain).encode()).hexdigest()
    return f"$sha256${salt}${digest}"


def check_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a stored hash.

    Supports both bcrypt (``$2b$...``) and the SHA-256 fallback
    (``$sha256$...``) formats.  An empty *hashed* value is treated as
    "no password set" and always returns ``True`` — this allows
    freshly-created pool objects to be claimed without needing a
    migration step to set an initial hash.

    Args:
        plain: The plaintext password the user typed.
        hashed: The stored hash string from the player object's
            ``password`` property.

    Returns:
        ``True`` if the password matches, ``False`` otherwise.

    Notes:
        Returns ``False`` (rather than raising) if *hashed* is in an
        unrecognised format, preventing login with a corrupted hash.
    """
    if not hashed:
        # No password set — accept anything (new / unclaimed object)
        return True
    if _HAS_BCRYPT and hashed.startswith('$2'):
        # bcrypt hash (starts with $2a$, $2b$, or $2y$)
        return _bcrypt.checkpw(plain.encode(), hashed.encode())
    if hashed.startswith('$sha256$'):
        # Fallback SHA-256 hash
        _, _, salt, digest = hashed.split('$', 3)
        return hashlib.sha256((salt + plain).encode()).hexdigest() == digest
    # Unrecognised format — deny access rather than guessing
    return False


# =========================================================================
#   Display screen (pre-login splash banner)
# =========================================================================

DEFAULT_SCREEN = r"""
    \ \        /      |
     \ \  \   /  _ \  |   __|   _ \   __ `__ \    _ \
      \ \  \ /   __/  |  (     (   |  |   |   |   __/
       \_/\_/  \___|__|_\|__| \___/  _|  _|  _| \___|
                       |   _ \
                       |  (   |
   ___|   |           _| \__|/                   _|         |  |
 \___ \   __ \    _` |   _` |   _ \ \ \  \   /  |     _` |  |  |
       |  | | |  (   |  (   |  (   | \ \  \ /   __|  (   |  |  |
 _____/  _| |_| \__,_| \__,_| \___/   \_/\_/   _|   \__,_| _| _|
"""
# No version in the art: the number that used to be here was a database
# version for a world this does not ship, and it had gone stale anyway.
#
# Note also that this fallback banner reads "Welcome to Shadowfall", the
# development world it came from.  It is only reached when neither
# config.display_screen nor display_screen.txt is present, and the shipped
# display_screen.txt does say MegaMOO -- but it is the wrong name to fall
# back to.


def load_display_screen(config: 'ServerConfig') -> str:
    """
    Load the splash text shown before the login prompt.

    Tries several sources in priority order so that server operators
    can customise the banner without editing code:

    Resolution order:
      1. ``config.display_screen`` — explicit path to a text file
         (set in the server config YAML/JSON).
      2. ``display_screen.txt`` in the current working directory —
         a convention-based default that requires no config.
      3. ``config.login_welcome`` — an inline string in config, for
         short messages without a separate file.
      4. The built-in ASCII art banner (``DEFAULT_SCREEN``).

    Args:
        config: The server configuration object.  Checked for
            ``display_screen`` (file path) and ``login_welcome``
            (inline string) attributes.

    Returns:
        The splash text as a string, ready to send to the player.

    Notes:
        File-read errors are logged as warnings and silently fall
        through to the next source, so a misconfigured path doesn't
        prevent login.
    """
    # 1. Explicit config path
    if config.display_screen:
        path = Path(config.display_screen)
        if path.is_file():
            try:
                return path.read_text(encoding='utf-8')
            except OSError as exc:
                logger.warning(f"Could not read display_screen {path}: {exc}")

    # 2. Convention: display_screen.txt in cwd
    cwd_screen = Path('display_screen.txt')
    if cwd_screen.is_file():
        try:
            return cwd_screen.read_text(encoding='utf-8')
        except OSError:
            pass

    # 3. Inline config string
    if config.login_welcome:
        return config.login_welcome

    # 4. Built-in art
    return DEFAULT_SCREEN


# =========================================================================
#   LoginHandler — async conversation driver
# =========================================================================

class LoginHandler:
    """
    Drives the login conversation over an async connection.

    This class encapsulates the entire pre-authentication dialogue:
    showing the splash screen, prompting for a username, verifying
    passwords, and (optionally) creating new accounts.

    It is intentionally transport-agnostic: call :meth:`run` with a
    *send* and *read_line* pair; it returns a :class:`MOOObject` on
    success or ``None`` on failure / disconnect.

    Usage::

        handler = LoginHandler(database, config)
        player = await handler.run(send=conn.send, read_line=conn.read_line)
        if player:
            # login succeeded — wire up the connection

    Attributes:
        database (Database): The live game database, used to look up
            player names, retrieve objects, and persist new accounts.
        config (ServerConfig): Server configuration, used to load the
            display screen and read game-wide settings.
        DEFAULT_PARENT (int): Object number of the parent prototype
            for new player objects (``#4`` = OCharacter prototype).
        PLAYER_POOL (int): Object number of the player pool container
            (``#2`` = PlayerObjectDB), which holds pre-created blank
            ``PlayerPlace`` objects ready to be claimed by new accounts.
        DEFAULT_LOCATION (int): Object number of the room where newly
            created (or newly logged-in) players are placed.  Read
            from ``settings.LOGIN_ROOM`` at class definition time.
    """

    # Parent for new players (#4 = OCharacter prototype).
    DEFAULT_PARENT = 4
    # Pool of pre-created player objects (#2 = PlayerObjectDB).
    PLAYER_POOL = 2
    # Starting location — read from settings.LOGIN_ROOM
    from .globals import LOGIN_ROOM
    DEFAULT_LOCATION = LOGIN_ROOM

    def __init__(self, database: 'Database', config: 'ServerConfig'):
        """
        Initialize the login handler.

        Args:
            database: The live game database for player lookup and
                object manipulation.
            config: Server configuration for display screen resolution
                and other login-related settings.
        """
        self.database = database
        self.config = config
        self.reconnect = False

    # -------------------------------------------------------------------
    #   Main login flow
    # -------------------------------------------------------------------

    async def run(self, send, read_line, max_attempts: int = 3) -> Optional[MOOObject]:
        """
        Execute the full login flow.

        Shows the splash screen, then loops up to *max_attempts* times
        prompting for a username.  Each iteration handles one of:

        * **"NEW"** — enters the account creation sub-flow via
          ``_create_flow()``.  If creation succeeds the new player
          object is returned immediately.
        * **Existing name** — looks up the player in the database,
          prompts for a password, verifies it, and checks that no
          other connection is already using that player object.

        Args:
            send: An ``async callable(str, **kwargs)`` that sends text
                to the client.  Must accept ``add_newline=False`` for
                prompt lines.
            read_line: An ``async callable() -> str`` that reads one
                line of input from the client.  Returns ``None`` or
                empty string on disconnect.
            max_attempts: Maximum number of username prompts before the
                handler gives up and disconnects the client.

        Returns:
            The authenticated player ``MOOObject``, or ``None`` if
            login failed (wrong password, too many attempts, or client
            disconnect).

        Notes:
            This method never raises — all internal errors are caught,
            logged, and presented to the player as user-friendly
            messages.
        """
        # Show splash banner. Lead with an SGR reset: raw mode bypasses the
        # dangling-style guard in _send, and a reconnecting client may still
        # be carrying attributes from a previous session.
        screen = load_display_screen(self.config)
        await send('\x1b[0m' + screen, raw=True)
        # Sent apart from the banner, and not raw: the splash goes out raw
        # so its ASCII art survives untouched, which also means colour codes
        # in it would print literally.  This line needs the dim grey.
        #
        # It used to read a version property off the in-world Globals
        # object, which held 'beta 0.7.0' -- an engine version copied into
        # the database once and left to rot, so a 0.9 server introduced
        # itself as 0.7.  SERVER_VERSION cannot drift.
        await send(f"%<245>({SERVER_VERSION})%n")
        await send("")

        for _ in range(max_attempts):
            # --- Username prompt ---
            await send("Enter your username or %<245>NEW%n to create a new account: ",
                       add_newline=False)

            name = await read_line()
            if name is None or name == '':
                # Disconnect or empty input — retry
                continue
            name = name.strip()
            if not name:
                continue

            # --- NEW account ---
            if name.upper() == 'NEW':
                player = await self._create_flow(send, read_line)
                if player:
                    return player
                # Creation failed — loop back to username prompt
                continue

            # --- Existing account ---
            # Check for inline password (username password on one line)
            parts = name.split(None, 1)
            inline_pw = None
            if len(parts) == 2:
                name, inline_pw = parts

            # Look up the player name in the database's name→objnum index
            player_num = self.database.get_player(name)
            if player_num is None:
                await send(f"No character named '{name}'.\n")
                continue

            try:
                player = self.database.get_object(player_num)
            except KeyError:
                await send("Error loading character.\n")
                continue

            # Get stored password hash
            stored_hash = ''
            if 'password' in player.properties:
                stored_hash = player.properties['password'].value or ''

            # If inline password was provided, use it; otherwise prompt
            if inline_pw is not None:
                pw = inline_pw
            else:
                await send("Password: ", add_newline=False)
                pw = await read_line()
                if pw is None:
                    return None
                pw = pw.strip()

            if stored_hash and not check_password(pw, stored_hash):
                await send("Incorrect password.\n")
                continue

            # Check for existing connection (direct or puppeted)
            from .network import find_connection_for_account, disconnect_for_takeover
            existing_conn = find_connection_for_account(player.objnum)
            if existing_conn:
                if inline_pw is None:
                    await send(f"{player.name} is already connected.\n")
                    await send("To reconnect, enter your username and password together.\n")
                    continue
                # Inline password = explicit reconnect request.
                # Return the ACTIVE character (may be ICharacter if puppeted).
                active_player = existing_conn.player_obj
                await disconnect_for_takeover(existing_conn)
                self.reconnect = True
                await send(f"Reconnecting as {active_player.name}...\n")
                return active_player

            return player

        # Exhausted all attempts
        await send("Too many attempts. Disconnecting.\n")
        return None

    # -------------------------------------------------------------------
    #   Account creation sub-flow
    # -------------------------------------------------------------------

    async def _create_flow(self, send, read_line) -> Optional[MOOObject]:
        """Sub-flow for creating a new account from the player pool.

        Walks the player through choosing a name and password, then
        claims a pre-created ``PlayerPlace`` object from the pool in
        ``#2``, renames it, sets the password hash, and moves it to
        ``DEFAULT_LOCATION``.

        The pool-based approach avoids runtime ``create()`` calls and
        keeps object numbering deterministic.  If the pool is empty,
        the player is told to contact the admins.

        Validation rules:
            * Name must be at least 3 characters.
            * Name must contain only ASCII letters (no spaces, digits,
              or special characters).
            * Name must not already be taken.

        Args:
            send: Async callable to send text to the client.
            read_line: Async callable to read one line from the client.

        Returns:
            The newly configured player ``MOOObject``, or ``None`` if
            any validation fails, the pool is empty, or an error
            occurs.
        """
        # --- Character name ---
        await send("Choose a character name: ", add_newline=False)
        name = await read_line()
        if name is None:
            return None
        name = name.strip()

        # Validate name length
        if len(name) < 3:
            await send("Name must be at least 3 characters.\n")
            return None
        # Validate name characters — letters only, no spaces or symbols
        if not name.isalpha():
            await send("Name must contain only letters.\n")
            return None
        # Check uniqueness against the database's player name index
        if self.database.get_player(name):
            await send(f"'{name}' is already taken.\n")
            return None

        # --- Password (with confirmation) ---
        await send("Choose a password: ", add_newline=False)
        pw1 = await read_line()
        if pw1 is None:
            return None
        pw1 = pw1.strip()

        await send("Confirm password: ", add_newline=False)
        pw2 = await read_line()
        if pw2 is None:
            return None
        pw2 = pw2.strip()

        if pw1 != pw2:
            await send("Passwords do not match.\n")
            return None

        # --- Claim a PlayerPlace object from the pool ---
        # #2 (PLAYER_POOL) is a container holding blank PlayerPlace
        # objects.  We scan its contents for the first unclaimed one.
        pool = self.database.get_object(self.PLAYER_POOL)
        player = None
        for obj in pool.contents:
            if obj.name == 'PlayerPlace':
                player = obj
                break

        if player is None:
            # Pool exhausted — no blank objects left.  An admin needs
            # to create more PlayerPlace objects in #2.
            await send(
                "There's been an error creating your account. "
                "Please email: devmind@deviousminds.com\n"
            )
            return None

        try:
            # --- Configure the claimed object as the new player ---
            # Set the noun (used for matching in commands like "look player")
            player.noun = name
            # Mark as a player object so the engine treats it specially
            player.set_flag(ObjectFlags.PLAYER)

            # Set display name and coloured name properties
            player.set_property('name', name)
            player.set_property('cname', name)

            # Hash and store the password
            pw_hash = hash_password(pw1) if pw1 else ''
            try:
                player.set_property('password', pw_hash)
            except KeyError:
                # Property doesn't exist yet on this pool object —
                # create it with read-only permissions so other players
                # can't inspect it.
                player.add_property('password', pw_hash, perms='r')

            # Move the new player to the starting room
            if self.database.valid(self.DEFAULT_LOCATION):
                player.move_to(self.DEFAULT_LOCATION, self.database)

            # Register the name→objnum mapping so future logins can
            # find this player by name.
            self.database.add_player(name, player.objnum)
            self.database.save_object(player)

            logger.info(f"New player created: {name} (#{player.objnum})")
            await send(f"Character '{name}' created. Welcome!\n")
            return player

        except Exception as exc:
            logger.error(f"Error creating player: {exc}", exc_info=True)
            await send("Error creating character.\n")
            return None
