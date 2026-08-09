"""
MegaMOO Configuration Module
=============================

This module handles all server configuration, including runtime settings,
default values, and configuration file management.  It is typically the first
module loaded during server startup and provides the :class:`ServerConfig`
dataclass that every other subsystem reads from.

Configuration Sources (Priority Order)
---------------------------------------
Settings are resolved in the following order -- higher-priority sources
override lower ones:

    1. **Command-line arguments** (highest priority) -- parsed in ``main.py``
       and applied directly to the :class:`ServerConfig` instance.
    2. **Environment variables** -- prefixed with ``MEGAMOO_`` and structured
       as ``MEGAMOO_<SECTION>_<SETTING>`` (see :meth:`ServerConfig.merge_from_env`).
    3. **Configuration file** (``config.json``) -- loaded via
       :meth:`ServerConfig.load` or :meth:`ServerConfig.load_or_create`.
    4. **Built-in defaults** (lowest priority) -- the default values declared
       on each dataclass field.

Architecture Notes
------------------
The configuration is split into focused dataclasses for clarity:

* :class:`NetworkConfig`  -- host, port, SSL, WebSocket settings.
* :class:`DatabaseConfig` -- database path, checkpointing, caching.
* :class:`ProtocolConfig` -- MUD protocol negotiation (MXP, GMCP, etc.).
* :class:`ApiConfig`      -- JSON API for external tools (verb editor).
* :class:`ServerConfig`   -- top-level container that aggregates all sections
  plus server-wide settings (name, MOTD, debug mode, etc.).

Validation is performed eagerly in :meth:`ServerConfig.__post_init__` so
that invalid configurations fail fast at startup rather than causing obscure
errors at runtime.

Usage::

    # Load from file, falling back to defaults
    config = ServerConfig.load_or_create('config.json')

    # Override from environment
    config.merge_from_env()

    # Access settings
    print(config.network.port)       # 7777
    print(config.database.path)      # 'game.db'
    print(config.protocol.enable_mxp)  # True

Copyright (c) 2026
License: MIT
"""

from .globals import SERVER_VERSION
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, field, asdict
import logging

from moo.globals import (DEFAULT_PORT, DEFAULT_AUTORELOAD_VERBS,
                         DEFAULT_AUTORELOAD_INTERVAL)

logger = logging.getLogger('megamoo.config')


# =============================================================================
# NETWORK CONFIGURATION
# =============================================================================

@dataclass
class NetworkConfig:
    """
    Network-related configuration settings.

    Controls how the server listens for incoming player connections,
    including plain TCP, SSL/TLS, and WebSocket transports.

    Attributes:
        host (str): Host address to bind to.  ``'0.0.0.0'`` listens on all
            interfaces; ``'127.0.0.1'`` restricts to localhost only.
        port (int): TCP port number for the main telnet listener.  With
            ``auto_port`` on this is only the *first* port tried.
        auto_port (bool): Whether a busy ``port`` makes the server scan
            upward for the next free one instead of failing to boot.  On
            by default so that a second database can be launched without
            hand-assigning a port.  Naming a port on the command line
            turns it off: a conflict then fails loudly rather than
            putting the game somewhere players aren't looking.
        port_scan_limit (int): How many consecutive ports to try when
            ``auto_port`` is on (``port`` .. ``port + limit - 1``).
        max_connections (int): Maximum simultaneous TCP connections the server
            will accept.  New connections beyond this limit are refused.
        connection_timeout (int): Seconds of idle time before a connection is
            automatically closed.  Set to ``0`` to disable timeouts.
        max_players (int): Maximum number of logged-in players.  ``0`` means
            unlimited.  Connections beyond this limit can connect but cannot
            log in.
        enable_ipv6 (bool): Whether to enable IPv6 dual-stack listening.
        tls_port (int): Port for an *additional* TLS listener.  ``0`` (the
            default) means no TLS listener.  This is deliberately a second
            port rather than a flag on the main one: the plain port has to
            keep working, because ``telnet`` cannot speak TLS and it is how
            most people first reach a world.  Both ports serve the same game.
        tls_cert (str): Filesystem path to the PEM-encoded certificate,
            including any intermediates.  Required when ``tls_port`` is set.
        tls_key (str): Filesystem path to the PEM-encoded private key.
            Required when ``tls_port`` is set.
        websocket_enabled (bool): Whether to start a WebSocket listener in
            addition to the telnet listener.  This listener also serves the
            browser client's static files.
        websocket_port (int): First port tried for the WebSocket listener
            (used only when ``websocket_enabled`` is ``True``).  With
            ``websocket_auto_port`` on this is only the *first* candidate.
        websocket_auto_port (bool): Whether a busy ``websocket_port`` makes
            the server scan forward for a free one.  Turned off when the
            operator names a port explicitly, so a conflict fails loudly.
        websocket_allowed_origins (list): Browser ``Origin`` values allowed
            to open a WebSocket.  Empty (the default) accepts any origin,
            which is right for localhost development.  On a public
            deployment, list your site's origins -- otherwise any web page
            the player visits can open an authenticated socket to your
            server in their name (cross-site WebSocket hijacking; the
            same-origin policy does *not* cover WebSockets).
    """
    host: str = '0.0.0.0'
    port: int = DEFAULT_PORT
    auto_port: bool = True
    port_scan_limit: int = 50
    max_connections: int = 100
    connection_timeout: int = 3600  # 1 hour
    max_players: int = 0  # 0 = unlimited
    enable_ipv6: bool = False
    tls_port: int = 0  # 0 = no TLS listener
    tls_cert: str = ''
    tls_key: str = ''
    websocket_enabled: bool = False
    websocket_port: int = 8888
    websocket_auto_port: bool = True
    websocket_allowed_origins: list = field(default_factory=list)


# =============================================================================
# DATABASE CONFIGURATION
# =============================================================================

@dataclass
class DatabaseConfig:
    """
    Database-related configuration settings.

    The MegaMOO database stores all in-game objects, properties, and verbs.
    These settings control persistence, checkpointing, and caching behaviour.

    Attributes:
        path (str): Filesystem path to the database file or directory.
        checkpoint_interval (int): Seconds between automatic checkpoint
            snapshots.  Checkpoints create a consistent recovery point.
        max_checkpoints (int): Maximum number of checkpoint files to retain
            on disk.  Older checkpoints are pruned automatically.
        transaction_log_enabled (bool): Whether to write a transaction log
            for crash recovery.  Disabling this improves write performance
            at the cost of durability.
        auto_save_interval (int): Seconds between automatic in-memory-to-disk
            saves.  This is separate from (and typically more frequent than)
            checkpointing.
        compress_checkpoints (bool): Whether to gzip checkpoint files to
            save disk space.
        backup_on_start (bool): Whether to create a full backup of the
            database file before the server begins modifying it.
        max_object_cache (int): Maximum number of :class:`~moo.objects.MOOObject`
            instances to keep in the in-memory LRU cache.  Higher values
            trade memory for faster repeated lookups.
    """
    path: str = 'game.db'
    checkpoint_interval: int = 3600  # 1 hour
    max_checkpoints: int = 10
    transaction_log_enabled: bool = True
    auto_save_interval: int = 300  # 5 minutes
    compress_checkpoints: bool = True
    backup_on_start: bool = True
    max_object_cache: int = 1000
    #: Where verb code reads and writes files, or '' for nowhere.
    #:
    #: A world legitimately wants files: logs, exports, notes it keeps
    #: outside the database.  What it needs from the engine is not a file
    #: API -- Python has one, and a house-brand read_file() would be
    #: exactly the sort of MOO-shaped wrapper for a thing Python already
    #: does that this engine is trying not to accumulate.
    #:
    #: What it needs is a *place*.  Code ported from a MOO with the FileIO
    #: extension says fileread("admin", "info") with no leading slash,
    #: because those servers rooted everything at a configured directory.
    #: Resolved against the process's working directory instead, that
    #: lands wherever the server happened to be started from.
    #:
    #: So the engine supplies the root and Python supplies the verbs::
    #:
    #:     Path(config.database.files_dir, 'admin', 'info').read_text()
    #:
    #: Empty by default.  This is not a sandbox and does not pretend to
    #: be one -- verb code is Python and can open anything the process
    #: can.  It is a default location, so that relative paths mean
    #: something deliberate.
    files_dir: str = ''


# =============================================================================
# PROTOCOL CONFIGURATION
# =============================================================================

@dataclass
class ProtocolConfig:
    """
    MUD client protocol negotiation settings.

    MegaMOO supports several optional MUD protocols that enhance the player
    experience for clients that support them.  Each protocol can be
    independently enabled or disabled.

    Attributes:
        enable_mxp (bool): Enable MXP (MUD eXtension Protocol) for rich
            clickable links and inline images.
        enable_gmcp (bool): Enable GMCP (Generic MUD Communication Protocol)
            for structured out-of-band data (character stats, room info, etc.).
        enable_msdp (bool): Enable MSDP (MUD Server Data Protocol), an
            alternative to GMCP for structured data exchange.
        enable_mssp (bool): Enable MSSP (MUD Server Status Protocol) so that
            MUD listing sites can auto-discover server metadata.
        enable_mccp (bool): Enable MCCP (MUD Client Compression Protocol) to
            compress downstream traffic, saving bandwidth on large text dumps.
        mxp_default_mode (str): Default MXP security mode for new connections.
            Must be one of ``'open'``, ``'secure'``, or ``'locked'``.

            - ``'open'``:   Client may use all MXP elements.
            - ``'secure'``: Only server-sent MXP elements are trusted (recommended).
            - ``'locked'``: MXP is negotiated but no elements are accepted.

        gmcp_packages (list): List of GMCP package names the server advertises
            during negotiation (e.g. ``['Core', 'Char', 'Room', 'Comm']``).
        telnet_options (dict): Low-level telnet option negotiation overrides.
            Keys are telnet option codes (int); values are booleans indicating
            whether the server should WILL/DO the option.
    """
    enable_mxp: bool = True
    enable_gmcp: bool = True
    enable_msdp: bool = True
    enable_mssp: bool = True
    enable_mccp: bool = True
    mxp_default_mode: str = 'secure'
    gmcp_packages: list = field(default_factory=lambda: [
        'Core', 'Char', 'Room', 'Comm'
    ])
    telnet_options: dict = field(default_factory=dict)


# =============================================================================
# API CONFIGURATION
# =============================================================================

@dataclass
class ApiConfig:
    """
    Configuration for the JSON-over-TCP API server.

    The API server allows external tools (verb editors, admin dashboards,
    monitoring scripts) to inspect and modify the running game state over
    a simple newline-delimited JSON protocol.  See :mod:`moo.api` for the
    protocol specification and command handlers.

    Attributes:
        enabled (bool): Whether to start the API server.  Defaults to
            ``False`` for security -- must be explicitly enabled.
        port (int): TCP port the API server listens on.  With
            ``auto_port`` on this is only the *first* port tried.
        auto_port (bool): Whether a busy ``port`` makes the server scan
            upward for the next free one instead of failing to boot.
            On by default so that several databases can each be started
            with ``--api`` without hand-assigning ports.  ``--api-port``
            turns it off: naming a port means you want that exact port.
        port_scan_limit (int): How many consecutive ports to try when
            ``auto_port`` is on (``port`` .. ``port + limit - 1``).
        info_path (str): Where to write the API discovery file -- a small
            JSON document naming the host/port/pid the API actually bound,
            so tools (``tools/megamoo_mcp.py``) can find a server whose
            port was auto-selected.  Empty (default) means "derive it from
            the database path" (``sf.db`` -> ``sf.db.api.json``); the
            file is removed on clean shutdown.  Set to ``'-'`` to disable.
        host (str): Host address to bind.  Defaults to ``'127.0.0.1'``
            (localhost only) to prevent remote access by default.
        auth_token (str): A shared secret token that API clients must
            present in their ``auth`` command.  If empty, authentication
            is disabled (any client can connect).
        testbot_objnum (int): Object number of the dedicated character
            the API's ``run_command`` plays as.  ``0`` (default) means
            find-or-create a character named "TestBot" under #5.

    Security Warning:
        If you set ``host`` to ``'0.0.0.0'``, the API will be accessible
        from any network interface.  Always set a strong ``auth_token``
        when exposing the API beyond localhost.
    """
    enabled: bool = False
    port: int = 7778
    auto_port: bool = True
    port_scan_limit: int = 50
    info_path: str = ''
    host: str = '127.0.0.1'
    auth_token: str = ''
    testbot_objnum: int = 0


# =============================================================================
# DEVELOPER CONFIGURATION
# =============================================================================

@dataclass
class DevConfig:
    """
    Developer-convenience settings.  Off by default and not meant for
    production: these trade safety/performance for a faster edit loop.

    Attributes:
        autoreload_verbs (bool): Whether to run a background watcher that
            polls the on-disk verb tree (``<moo_verb_path>/<objnum>/*.py``)
            and hot-loads changed files into the live database.  Editing a
            verb file on disk then takes effect without an explicit
            ``@reload``.  Default comes from ``globals.py``
            (``DEFAULT_AUTORELOAD_VERBS``) -- in production, verb code
            should only change through in-game tools, not stray disk edits.
        autoreload_interval (float): Seconds between polls of the verb tree
            when ``autoreload_verbs`` is enabled.
    """
    autoreload_verbs: bool = DEFAULT_AUTORELOAD_VERBS
    autoreload_interval: float = DEFAULT_AUTORELOAD_INTERVAL


# =============================================================================
# MAIN SERVER CONFIGURATION
# =============================================================================

@dataclass
class ServerConfig:
    """
    Top-level server configuration container.

    Aggregates all configuration sub-sections (:class:`NetworkConfig`,
    :class:`DatabaseConfig`, :class:`ProtocolConfig`, :class:`ApiConfig`)
    and adds server-wide settings like the server name, MOTD, and debug
    flags.

    This class also provides the full configuration lifecycle:

    * **Loading** -- :meth:`load` (from file), :meth:`from_dict` (from dict),
      :meth:`load_or_create` (load with fallback to defaults).
    * **Saving** -- :meth:`save` (to JSON file), :meth:`to_dict` (to dict).
    * **Merging** -- :meth:`merge_from_env` (overlay environment variables).
    * **Validation** -- :meth:`validate` (called automatically on init).

    Attributes:
        network (NetworkConfig):   Network/connection settings.
        database (DatabaseConfig): Database/persistence settings.
        protocol (ProtocolConfig): MUD protocol negotiation settings.
        api (ApiConfig):           External API server settings.
        server_name (str):         Human-readable server name shown in MSSP
                                   listings and the login banner.
        version (str):             Server version string.
        motd (str):                Message of the Day displayed after login.
        login_welcome (str):       Text shown on the login screen before the
                                   player enters credentials.
        display_screen (str):      Path to a text file whose contents are
                                   shown before the login prompt.
        max_command_length (int):  Maximum characters allowed in a single
                                   player command.  Longer input is truncated.
        max_object_moves_per_second (int): Rate limit for object moves, used
                                   as an anti-spam / anti-abuse measure.
        enable_color (bool):       Whether ANSI colour codes are processed
                                   and sent to clients.
        debug_mode (bool):         Enables verbose logging and developer-
                                   facing error messages.
        log_level (str):           Python logging level name (e.g. ``'INFO'``,
                                   ``'DEBUG'``, ``'WARNING'``).
    """
    network: NetworkConfig = field(default_factory=NetworkConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    protocol: ProtocolConfig = field(default_factory=ProtocolConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
    dev: DevConfig = field(default_factory=DevConfig)

    server_name: str = 'MegaMOO Server'
    version: str = SERVER_VERSION
    motd: str = 'Welcome to MegaMOO!'
    login_welcome: str = ''
    display_screen: str = ''  # Path to text file shown before login prompt
    max_command_length: int = 1000
    max_object_moves_per_second: int = 10
    enable_color: bool = True
    debug_mode: bool = False
    log_level: str = 'INFO'

    def __post_init__(self):
        """Validate configuration immediately after dataclass initialisation."""
        self.validate()

    # -------------------------------------------------------------------------
    # Validation
    # -------------------------------------------------------------------------

    def validate(self):
        """
        Validate all configuration settings for correctness.

        Called automatically by :meth:`__post_init__` so that invalid configs
        fail fast at construction time.  Can also be called manually after
        mutating settings.

        Raises:
            ValueError: If any setting is out of range or inconsistent.
                The error message identifies the specific setting and the
                constraint that was violated.

        Checks performed:
            - Port numbers are in the valid TCP range (1--65535).
            - ``max_connections`` is at least 1.
            - Timeout values are non-negative.
            - If ``tls_port`` is set, ``tls_cert`` and ``tls_key`` are
              given, point at existing files, and the port is neither out
              of range nor the plain port.  A cert without a port is an
              error too: it looks like TLS is on when nothing would
              listen.
            - ``checkpoint_interval`` is non-negative.
            - ``max_checkpoints`` is at least 1.
            - If the API is enabled, its port must be valid.
            - ``mxp_default_mode`` is one of ``'open'``, ``'secure'``,
              ``'locked'``.
        """
        # Validate network settings
        if not (1 <= self.network.port <= 65535):
            raise ValueError(f"Invalid port number: {self.network.port}")

        if self.network.port_scan_limit < 1:
            raise ValueError("network.port_scan_limit must be at least 1")

        if self.network.max_connections < 1:
            raise ValueError("max_connections must be at least 1")

        if self.network.connection_timeout < 0:
            raise ValueError("connection_timeout must be non-negative")

        # Validate TLS configuration.  Every one of these refuses to start
        # rather than starting without encryption: a world that quietly
        # serves plaintext when you asked for TLS is the failure this
        # whole feature exists to avoid.  The previous settings validated
        # exactly like this and then were never read by anything.
        if self.network.tls_port:
            if not (0 < self.network.tls_port < 65536):
                raise ValueError(f"tls_port out of range: {self.network.tls_port}")
            if self.network.tls_port == self.network.port:
                raise ValueError(
                    f"tls_port {self.network.tls_port} is the plain port; "
                    "TLS needs a port of its own")
            if not self.network.tls_cert or not self.network.tls_key:
                raise ValueError(
                    "tls_port is set but tls_cert/tls_key are not")
            for label, path in (('certificate', self.network.tls_cert),
                                ('key', self.network.tls_key)):
                if not os.path.exists(path):
                    raise ValueError(f"TLS {label} not found: {path}")
        elif self.network.tls_cert or self.network.tls_key:
            raise ValueError(
                "tls_cert/tls_key given without tls_port, so no TLS "
                "listener would start; set tls_port to serve them")

        # Validate database settings
        if self.database.checkpoint_interval < 0:
            raise ValueError("checkpoint_interval must be non-negative")

        if self.database.max_checkpoints < 1:
            raise ValueError("max_checkpoints must be at least 1")

        # Validate API settings
        if self.api.enabled and not (1 <= self.api.port <= 65535):
            raise ValueError(f"Invalid API port number: {self.api.port}")

        if self.api.port_scan_limit < 1:
            raise ValueError("api.port_scan_limit must be at least 1")

        # Validate developer settings
        if self.dev.autoreload_interval <= 0:
            raise ValueError("dev.autoreload_interval must be positive")

        # Validate protocol settings -- MXP mode must be a known value
        valid_mxp_modes = ['open', 'secure', 'locked']
        if self.protocol.mxp_default_mode not in valid_mxp_modes:
            raise ValueError(
                f"Invalid MXP mode: {self.protocol.mxp_default_mode}. "
                f"Must be one of {valid_mxp_modes}"
            )

        logger.info("Configuration validated successfully")

    # -------------------------------------------------------------------------
    # Serialisation
    # -------------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the entire configuration tree to a plain dictionary.

        Nested dataclasses (:class:`NetworkConfig`, etc.) are converted via
        :func:`dataclasses.asdict`.  The resulting dict is JSON-serialisable
        and suitable for writing to a config file.

        Returns:
            Dict[str, Any]: Configuration as a nested dictionary.
        """
        return {
            'network': asdict(self.network),
            'database': asdict(self.database),
            'protocol': asdict(self.protocol),
            'api': asdict(self.api),
            'dev': asdict(self.dev),
            'server_name': self.server_name,
            'version': self.version,
            'motd': self.motd,
            'login_welcome': self.login_welcome,
            'display_screen': self.display_screen,
            'max_command_length': self.max_command_length,
            'max_object_moves_per_second': self.max_object_moves_per_second,
            'enable_color': self.enable_color,
            'debug_mode': self.debug_mode,
            'log_level': self.log_level,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ServerConfig':
        """
        Construct a :class:`ServerConfig` from a plain dictionary.

        This is the inverse of :meth:`to_dict`.  Nested section keys
        (``'network'``, ``'database'``, ``'protocol'``, ``'api'``) are
        extracted and used to build the corresponding sub-dataclasses.
        Unknown top-level keys are silently ignored, making the format
        forward-compatible.

        Args:
            data (Dict[str, Any]): Configuration dictionary, typically
                loaded from a JSON file.

        Returns:
            ServerConfig: A fully constructed and validated configuration.

        Raises:
            TypeError: If a sub-section dictionary contains keys that do
                not match the target dataclass fields.
            ValueError: If validation fails (propagated from ``__post_init__``).
        """
        # Extract nested configuration sections
        network_data = data.get('network', {})
        database_data = data.get('database', {})
        protocol_data = data.get('protocol', {})
        api_data = data.get('api', {})
        dev_data = data.get('dev', {})

        # Create sub-config dataclasses from their dictionaries
        network = NetworkConfig(**network_data)
        database = DatabaseConfig(**database_data)
        protocol = ProtocolConfig(**protocol_data)
        api = ApiConfig(**api_data)
        dev = DevConfig(**dev_data)

        # Filter remaining top-level keys to only those that are valid
        # ServerConfig fields, ignoring unknown keys for forward compatibility
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        config_data = {k: v for k, v in data.items()
                      if k not in ['network', 'database', 'protocol', 'api', 'dev']
                      and k in valid_fields}

        return cls(
            network=network,
            database=database,
            protocol=protocol,
            api=api,
            dev=dev,
            **config_data
        )

    # -------------------------------------------------------------------------
    # File I/O
    # -------------------------------------------------------------------------

    def save(self, path: str):
        """
        Serialise and write the configuration to a JSON file.

        The file is written with 2-space indentation for human readability.
        If the file already exists it is overwritten.

        Args:
            path (str): Filesystem path for the output JSON file.

        Raises:
            IOError: If the file cannot be opened or written.
        """
        try:
            with open(path, 'w') as f:
                json.dump(self.to_dict(), f, indent=2)
            logger.info(f"Configuration saved to {path}")
        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")
            raise

    @classmethod
    def load(cls, path: str) -> 'ServerConfig':
        """
        Load a configuration from a JSON file.

        Args:
            path (str): Filesystem path to a JSON configuration file.

        Returns:
            ServerConfig: The loaded and validated configuration.

        Raises:
            FileNotFoundError: If *path* does not exist.
            json.JSONDecodeError: If *path* is not valid JSON.
            ValueError: If validation fails after loading.
        """
        try:
            with open(path, 'r') as f:
                data = json.load(f)
            logger.info(f"Configuration loaded from {path}")
            return cls.from_dict(data)
        except FileNotFoundError:
            logger.warning(f"Configuration file not found: {path}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in configuration file: {e}")
            raise

    @classmethod
    def load_or_create(cls, path: str) -> 'ServerConfig':
        """
        Load configuration from file, or create a default config if not found.

        This is the recommended entry point for server startup.  If the
        config file does not exist, a default :class:`ServerConfig` is
        created, saved to *path* for future runs, and returned.

        Args:
            path (str): Filesystem path to the JSON configuration file.

        Returns:
            ServerConfig: The loaded or newly created default configuration.
        """
        try:
            return cls.load(path)
        except FileNotFoundError:
            logger.info("Creating default configuration")
            config = cls()
            config.save(path)
            return config

    # -------------------------------------------------------------------------
    # Environment variable overlay
    # -------------------------------------------------------------------------

    def merge_from_env(self):
        """
        Override configuration values from environment variables.

        Scans all environment variables for the ``MEGAMOO_`` prefix and
        applies matching values.  The naming convention is::

            MEGAMOO_<SECTION>_<SETTING>=value

        where ``<SECTION>`` is one of ``NETWORK``, ``DATABASE``, ``PROTOCOL``,
        ``DEV``, ``API``, or a top-level setting name, and ``<SETTING>``
        is the field name within that section.  Multi-word settings use
        underscores.

        Type conversion is automatic:
            - Strings that look like integers become ``int``.
            - ``"true"``/``"yes"`` become ``True``; ``"false"``/``"no"``
              become ``False``.
            - Everything else remains a ``str``.

        Examples::

            MEGAMOO_NETWORK_PORT=8888           -> config.network.port = 8888
            MEGAMOO_DATABASE_PATH=/data/game.db -> config.database.path = '/data/game.db'
            MEGAMOO_PROTOCOL_ENABLE_MXP=false   -> config.protocol.enable_mxp = False
            MEGAMOO_API_INFO_PATH=/tmp/x.json   -> config.api.info_path = '/tmp/x.json'
            MEGAMOO_DEBUG_MODE=true              -> config.debug_mode = True

        Note:
            ``MEGAMOO_API_TOKEN`` is *not* one of these -- the API's field
            is ``auth_token``, and the name belongs to the MCP bridge.
            Pass the server's token with ``--api-token``.
        """
        prefix = 'MEGAMOO_'

        for key, value in os.environ.items():
            if not key.startswith(prefix):
                continue

            # Parse key: MEGAMOO_NETWORK_PORT -> ['network', 'port']
            parts = key[len(prefix):].lower().split('_')

            if len(parts) < 2:
                continue

            section = parts[0]
            setting = '_'.join(parts[1:])

            # Route to the appropriate config section
            if section == 'network' and hasattr(self.network, setting):
                setattr(self.network, setting, self._convert_env_value(value))
            elif section == 'database' and hasattr(self.database, setting):
                setattr(self.database, setting, self._convert_env_value(value))
            elif section == 'protocol' and hasattr(self.protocol, setting):
                setattr(self.protocol, setting, self._convert_env_value(value))
            elif section == 'dev' and hasattr(self.dev, setting):
                setattr(self.dev, setting, self._convert_env_value(value))
            elif section == 'api' and hasattr(self.api, setting):
                setattr(self.api, setting, self._convert_env_value(value))
            elif hasattr(self, setting):
                setattr(self, setting, self._convert_env_value(value))

        logger.info("Configuration merged from environment variables")

    def _convert_env_value(self, value: str) -> Any:
        """
        Convert an environment variable string to the appropriate Python type.

        Conversion is attempted in this order:
            1. ``int`` -- if the string is composed entirely of digits
               (with optional leading ``-``).
            2. ``bool`` -- if the string is one of the word-form boolean
               literals (``true``/``yes``/``false``/``no``), case-insensitive.
               Note: ``'0'``/``'1'`` are treated as integers, not booleans.
            3. ``str`` -- the raw string value is returned as-is.

        Args:
            value (str): The raw string from the environment.

        Returns:
            The converted value (``int``, ``bool``, or ``str``).
        """
        # Try integer first (before boolean, so '0'/'1' stay as ints)
        try:
            return int(value)
        except ValueError:
            pass

        # Try boolean (only match word-form strings, not '0'/'1')
        if value.lower() in ('true', 'yes'):
            return True
        if value.lower() in ('false', 'no'):
            return False

        # Return as string
        return value
