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
import hmac
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

#: PBKDF2 iterations.  OWASP's 2023 floor for PBKDF2-HMAC-SHA256 is
#: 600,000; the cost is a few hundred milliseconds once per login.
PBKDF2_ROUNDS = 600_000


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
    # PBKDF2-HMAC-SHA256, stdlib, no dependency.  This is not a fallback
    # in practice -- it is the shipping configuration.  megamoo declares
    # no dependencies, so `pip install megamoo` never brings bcrypt, and
    # every real deployment stores passwords with whatever this returns.
    #
    # It used to return one unstretched SHA-256, which a GPU tries at
    # billions of guesses a second; the wizard password shipped in the
    # PyPI wheel was recovered from its hash in under a second with a
    # 28-word list.  Stretching is the whole defence when the hash leaks.
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        'sha256', plain.encode(), salt.encode(), PBKDF2_ROUNDS).hex()
    return f"$pbkdf2${PBKDF2_ROUNDS}${salt}${digest}"


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
    if hashed.startswith('$pbkdf2$'):
        try:
            _, _, rounds, salt, digest = hashed.split('$', 4)
            computed = hashlib.pbkdf2_hmac(
                'sha256', plain.encode(), salt.encode(), int(rounds)).hex()
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(computed, digest)
    if hashed.startswith('$sha256$'):
        # Legacy, from before the stretch.  Still verified so worlds
        # created earlier keep working; hash_password never produces it
        # again, so these convert as players change their passwords.
        _, _, salt, digest = hashed.split('$', 3)
        computed = hashlib.sha256((salt + plain).encode()).hexdigest()
        return hmac.compare_digest(computed, digest)
    # Unrecognised format — deny access rather than guessing
    return False


# =========================================================================
#   Display screen (pre-login splash banner)
# =========================================================================

DEFAULT_SCREEN = r"""
\ \        /    |                              |
 \ \  \   / _ \ |  __|  _ \  __ `__ \   _ \    __|  _ \
  \ \  \ /  __/ | (    (   | |   |   |  __/    |   (   |
   \_/\_/ \___|_|\___|\___/ _|  _|  _|\___|   \__|\___/

  \  |                   \  |  _ \   _ \
 |\/ |  _ \  _` |  _` | |\/ | |   | |   |
 |   |  __/ (   | (   | |   | |   | |   |
_|  _|\___|\__, |\__,_|_|  _|\___/ \___/
           |___/
"""
# No version in the art: the number that used to be here was a database
# version for a world this does not ship, and it had gone stale anyway.
#
# This art used to read "Welcome to Shadowfall" -- the development world
# the engine was carved out of.  Every `megamoo init` world reached it,
# because a fresh game had no display_screen.txt of its own, so the first
# thing a new builder saw was somebody else's game announcing itself.  A
# fallback has to name the thing that is actually running.
#
# `megamoo init` now also writes this text out as display_screen.txt, so
# the ordinary way to change it is editing a file in your own world
# rather than editing the engine.  This constant is what worlds created
# before that, or with their file deleted, fall back to.


def _world_version(database) -> str:
    """
    The version this *world* declares, or '' if it declares none.

    ``$version`` -- a string on #0, reachable from verb code as
    ``sysobj('version')`` like any other $reference.  #0 exists in every
    world by definition, so there is one place to look and nothing to
    configure.  A world that never sets it shows the engine's version,
    which is right for a starter world nobody has made into a game yet.

    Never raises: the splash has to render even if the database is odd.
    """
    try:
        sysobj = database.get_object(0)
        value = getattr(sysobj, 'version', None)
        return str(value).strip() if value else ''
    except Exception:
        return ''


def _world_name(database, config) -> str:
    """
    What this world calls itself, for a client that can show a name.

    ``$title`` on #0, the same shape as ``$version`` above and for the same
    reason: #0 exists in every world, so there is one place to look and
    nothing to configure.

    Deliberately not ``$name``.  Every object carries a native ``name``,
    and #0's is "SystemObject" -- so ``getattr(sysobj, 'name')`` always
    succeeds and never means what was asked.  ``$version`` gets away with
    the pattern because no object has a native ``version`` to collide
    with.  This one needed a word of its own.

    Falls back to ``server_name`` from the config, which a world nobody
    has renamed answers with "MegaMOO Server" -- honest, if uninspiring.

    Never raises: the splash has to render even if the database is odd.
    """
    try:
        value = getattr(database.get_object(0), 'title', None)
        if value:
            return str(value).strip()
    except Exception:
        pass
    return getattr(config, 'server_name', '') or ''


#: Filenames a world can drop beside ``display_screen.txt`` to give the
#: browser client a splash image.  Checked in this order, so a world that
#: ships more than one gets the sharpest: vector, then modern raster, then
#: whatever it has.  Nothing here reaches a terminal -- telnet gets the
#: ASCII banner, which is the only thing it can show.
SPLASH_IMAGE_NAMES = ('splash.svg', 'splash.webp', 'splash.png',
                      'splash.jpg', 'splash.jpeg', 'splash.gif')


def find_splash_image(directory='.') -> Optional[str]:
    """
    The world's splash image filename, or None if it has none.

    Looked for beside ``display_screen.txt`` in the world's own directory,
    because a splash is the world's, not the engine's -- it should travel
    in the game directory `megamoo init` creates and version-controls, not
    inside the installed package.

    Returns a bare filename rather than a path: it is about to become a
    URL the browser asks for, and the web server resolves it back against
    this same directory.
    """
    try:
        for name in SPLASH_IMAGE_NAMES:
            if (Path(directory) / name).is_file():
                return name
    except OSError:
        pass
    return None


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

    # 2. Convention: display_screen.txt beside the world, then in cwd.
    #
    # Beside the world first, because that is where `megamoo init` puts
    # it and it is a property of the world rather than of wherever you
    # happened to be standing.  Serving a world by path from somewhere
    # else -- `megamoo /srv/games/mygame/world.db` -- used to fall
    # through to the built-in banner with no error at all: the right
    # world, somebody else's name on the door.
    candidates = []
    db_path = getattr(getattr(config, 'database', None), 'path', None)
    if db_path:
        candidates.append(Path(db_path).expanduser().resolve().parent
                          / 'display_screen.txt')
    candidates.append(Path('display_screen.txt'))
    for screen in candidates:
        if screen.is_file():
            try:
                return screen.read_text(encoding='utf-8')
            except OSError:
                continue

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
        #
        # Then dim grey, xterm 245 -- the same colour the version line below
        # asks for as `&<245>`, written here as the escape it compiles to,
        # because a raw send does not read MOO colour codes. The banner is
        # chrome: it should not arrive louder than the prompt the player is
        # meant to answer, and dimming it puts those two in the right order.
        #
        # Done here rather than in the browser client's stylesheet so that a
        # terminal and a browser show the same banner. It is one artifact,
        # and this line is the only place both transports read it from.
        #
        # Reset again at the end, or a terminal keeps the attribute and
        # everything after the splash comes out dim as well.
        #
        # A world may also ship a splash image, which a browser shows in
        # the banner's place. The ASCII still goes out: it is what a
        # terminal shows, it is what the browser falls back to if the image
        # does not load, and sending it unconditionally means the two
        # transports never disagree about whether there is a banner.
        screen = load_display_screen(self.config)
        image = find_splash_image()
        await send('\x1b[0m\x1b[38;5;245m' + screen + '\x1b[0m', raw=True,
                   image=({'src': image,
                           'alt': _world_name(self.database, self.config)}
                          if image else None))
        # Sent apart from the banner, and not raw: the splash goes out raw
        # so its ASCII art survives untouched, which also means colour codes
        # in it would print literally.  This line needs the dim grey.
        #
        # $version if the world declares one, otherwise the engine's.
        #
        # A player arriving at your game cares which *game* this is, not
        # which server it runs on -- and a world under development has a
        # version of its own that moves independently.  $version is where
        # a world says so; leave it unset and the engine's version is
        # shown, which is the right answer for a starter world that has
        # not been made into anything yet.
        #
        # This is not the old arrangement coming back.  That read an
        # *engine* version copied into the database once and left to rot,
        # so a 0.9 server introduced itself as 0.7.  A world version
        # cannot rot in that way, because nothing else is entitled to
        # write it.
        # banner=True: this line belongs to the splash above it rather than
        # to the conversation, so a client that centres its banner centres
        # this with it. A terminal ignores it -- centring there would mean
        # padding to the window width, and the ASCII art it sits under is
        # left-aligned anyway.
        await send(f"&<245>({_world_version(self.database) or SERVER_VERSION})&n",
                   banner=True)
        await send("")

        for _ in range(max_attempts):
            # --- Username prompt ---
            await send("Enter your username or &<245>NEW&n to create a new account: ",
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

            # Set the display name
            player.set_property('name', name)

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
