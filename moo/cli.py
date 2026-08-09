#!/usr/bin/env python3
"""
MegaMOO Server - A Python Implementation of LambdaMOO

This is a complete reimplementation of the LambdaMOO server in Python,
combining the best features of LambdaMOO's object-oriented programming
model with modern Python capabilities and Evennia's network protocols.

Usage:
    ./megamoo.py <database_file> [new_database] [port]
    
Examples:
    ./megamoo.py game.db                    # Start server with game.db on default port
    ./megamoo.py game.db new.db 7777       # Create new.db from game.db, run on port 7777
    ./megamoo.py -h                         # Show help
    
Features:
    - Hierarchical object inheritance (like LambdaMOO)
    - On-the-fly verb editing and programming
    - Built-in command parser with argument parsing
    - Disk-based persistent storage (not memory-based)
    - Multiple database instances can run simultaneously
    - Full MOO programming language support
    - MXP, GMCP, and other MUD protocols via Evennia integration
    - ANSI color coding and formatting
    
Architecture:
    The server consists of several key subsystems:
    
    1. Object System (moo/objects.py)
       - MOOObject base class with properties and verbs
       - Hierarchical inheritance
       - Property and verb resolution
       
    2. Database Layer (moo/database.py)
       - Disk-based object persistence
       - Transaction support
       - Incremental checkpointing
       
    3. Parser (moo/parser.py)
       - Command parsing with argument extraction
       - Verb matching and resolution
       - Preposition handling
       
    4. Verb System (moo/verbs.py)
       - Verb compilation and execution
       - Permission checking
       - Task management
       
    5. Network Layer (moo/network.py)
       - Protocol negotiation (Telnet, MXP, GMCP, etc.)
       - Connection management
       - Text encoding/color codes
       
    6. Builtin Functions (moo/builtins.py)
       - All LambdaMOO built-in functions
       - Database manipulation
       - String and list operations

Copyright (c) 2026
License: MIT

Based on:
    - LambdaMOO Server by Pavel Curtis and others
    - Evennia MUD Engine by Griatch and contributors
"""

import sys
import os
import argparse
import pathlib
import secrets
import logging
import logging.handlers
import signal
from pathlib import Path

# Configure logging before any other imports
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.handlers.RotatingFileHandler(
            'megamoo.log', maxBytes=10*1024*1024, backupCount=5
        ),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('megamoo')

# MegaMOO imports
from moo.database import Database
from moo.server import MegaMOOServer, run_server
from moo.config import ServerConfig
from moo.globals import SERVER_VERSION


def _add_game_package_to_path(database):
    """
    Make a game's own Python importable from its verbs.

    A game directory may carry a ``game/`` package beside its world --
    combat tables, chargen data, economy rules; everything that is about
    *this* world rather than about running any world.  Putting the game
    directory on sys.path means a verb reaches it with an ordinary
    import::

        from game.combat import swing

    which is the same spelling verbs already use for ``moo.objects``.
    Without this the only place such code could live was inside the
    engine, which is how an engine gets forked: sfdev grew combat_data,
    chargen_data, moo_files and grid/ under moo/, and nine of its verbs
    import from them, so its game cannot run on the shipped engine.

    Args:
        database: Path to the world being served.
    """
    if not database:
        return
    root = pathlib.Path(database).expanduser().resolve().parent
    if (root / 'game' / '__init__.py').is_file():
        entry = str(root)
        if entry not in sys.path:
            sys.path.insert(0, entry)
            logger.info(f'Game package: {root / "game"}')


def _state_dir() -> pathlib.Path:
    """Where cross-world state lives: the shared API token, run files."""
    return pathlib.Path(
        os.environ.get('MEGAMOO_STATE_DIR', pathlib.Path.home() / '.megamoo'))


def _shared_api_token() -> str:
    """
    Read the shared API token, creating one the first time.

    One token for every world on the machine, so a tool configured once
    keeps working when you start a different database.  Written 0600 and
    never logged.
    """
    token_file = pathlib.Path(
        os.environ.get('MEGAMOO_TOKEN_FILE', _state_dir() / 'token'))
    if token_file.is_file() and token_file.stat().st_size:
        return token_file.read_text().strip()
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(16)
    token_file.write_text(token + '\n')
    token_file.chmod(0o600)
    print(f'megamoo: generated a new API token in {token_file}')
    return token


def _read_game_toml(directory='.'):
    """
    Read ``megamoo.toml`` from *directory*, or return {} if there is none.

    ``megamoo init`` writes this file with a comment saying it is "what
    to serve, and where", and nothing read it.  The database was picked
    by globbing the directory instead, and ``[server] port`` did nothing
    at all -- edit it, restart, and the server came up on 6770 anyway.

    Returns a flat dict with the keys this function knows about, so a
    caller never has to reach into the file's shape:
    ``{'database': str, 'port': int, 'verbs': str, 'name': str}``.
    """
    path = pathlib.Path(directory) / 'megamoo.toml'
    if not path.is_file():
        return {}
    try:
        import tomllib
    except ImportError:
        # tomllib arrived in 3.11 and this package supports 3.10.  Rather
        # than take a dependency for one small file, read the two keys
        # that matter.  A 3.10 user who wants the full grammar can
        # upgrade; what they must not get is silence.
        out = {}
        section = ''
        for line in path.read_text().splitlines():
            line = line.split('#', 1)[0].strip()
            if line.startswith('['):
                section = line.strip('[]')
            elif '=' in line:
                k, _, v = line.partition('=')
                v = v.strip().strip('"').strip("'")
                k = k.strip()
                if section == 'game' and k in ('database', 'verbs', 'name'):
                    out[k] = v
                elif section == 'server' and k == 'port' and v.isdigit():
                    out['port'] = int(v)
        return out
    data = tomllib.loads(path.read_text())
    game = data.get('game', {}) or {}
    server = data.get('server', {}) or {}
    out = {k: game[k] for k in ('database', 'verbs', 'name') if k in game}
    if isinstance(server.get('port'), int):
        out['port'] = server['port']
    return out


def _only_database_here():
    """
    The single ``.db`` in the working directory, or None.

    Convenience with a hard edge: if there are two, say so rather than
    picking one, because guessing which world to serve is the kind of
    help that costs an afternoon.
    """
    found = sorted(pathlib.Path('.').glob('*.db'))
    if len(found) == 1:
        return str(found[0])
    if not found:
        print('megamoo: no .db here; name one: megamoo <database>',
              file=sys.stderr)
    else:
        names = ', '.join(p.name for p in found)
        print(f'megamoo: several databases here ({names}); '
              f'name one: megamoo <database>', file=sys.stderr)
    raise SystemExit(2)


def _apply_dev_defaults(args):
    """
    Everything the old ``./mm`` script did, minus its two fatal habits.

    That script cd'd into the engine checkout, so it could only ever run
    a database living inside the engine -- the same directory conflation
    the packaging exists to end -- and it hardcoded one machine's Python.
    What it did well was the part worth keeping: a shared token, a
    discovery file so tooling can find the world, autoreload, and picking
    the obvious database.  None of that should have been a shell script
    only its author had.

    Args:
        args: Parsed arguments, modified in place.
    """
    # megamoo.toml first, then the lone .db here.  The file is the
    # world's own statement of what it is, and globbing the directory is
    # the fallback for a game that has not got one.
    game = _read_game_toml()
    if not args.database:
        args.database = game.get('database') or _only_database_here()
    if args.port is None and game.get('port'):
        # A flag still wins -- it is the more specific instruction.
        args.port = game['port']

    args.api = True
    if not args.api_token:
        args.api_token = _shared_api_token()

    # Publish where this world is listening.  Without it, tooling has to
    # be told the port by hand every time -- and silently loses the world
    # when it changes.
    if not os.environ.get('MEGAMOO_API_INFO_PATH'):
        run_dir = _state_dir() / 'run'
        run_dir.mkdir(parents=True, exist_ok=True)
        key = str(pathlib.Path(args.database).resolve()).replace('/', '_')
        os.environ['MEGAMOO_API_INFO_PATH'] = str(run_dir / f'{key}.api.json')

    # The browser client, on, without being asked.
    #
    # It was behind a flag people had to know existed, which is a poor
    # way to ship a first-party client -- especially the one a newcomer
    # is most likely to want, since it needs no telnet client and no
    # explaining.  Dev mode is local and single-developer, so there is no
    # reason to make it opt-in here.  A public deployment still says
    # --web deliberately, because serving it without --web-origins is a
    # real exposure rather than a preference.
    args.web = True

    os.environ.setdefault('MEGAMOO_DEV_AUTORELOAD_VERBS', 'true')


class MegaMOO:
    """
    Main MegaMOO server application.
    
    This class manages the server lifecycle, including:
    - Command-line argument parsing
    - Database initialization
    - Server startup and shutdown
    - Signal handling for graceful termination
    
    Attributes:
        config (ServerConfig): Server configuration object
        database (Database): The active MOO database
        server (MOOServer): The network server instance
    """
    
    def __init__(self):
        """Initialize the MegaMOO application."""
        self.config = None
        self.database = None
        self.server = None
        self._shutdown = False
        
    def parse_arguments(self):
        """
        Parse command-line arguments.
        
        Returns:
            argparse.Namespace: Parsed arguments
            
        The argument format follows LambdaMOO convention:
            ./megamoo.py <database> [new_database] [port]
        
        However, we also support modern argument flags for clarity.
        """
        parser = argparse.ArgumentParser(
            description='MegaMOO - A Python implementation of LambdaMOO',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  %(prog)s game.db                     Start with existing database
  %(prog)s game.db new.db              Create new database from template
  %(prog)s game.db new.db 7777         Specify custom port
  %(prog)s --input game.db --port 8888 Using flags (recommended)
            """
        )
        
        # Positional arguments (LambdaMOO style)
        parser.add_argument(
            'database',
            nargs='?',
            help='Database file to load'
        )
        parser.add_argument(
            'new_database',
            nargs='?',
            help='New database file to create (optional)'
        )
        parser.add_argument(
            'port',
            nargs='?',
            type=int,
            # SUPPRESS: this positional shares dest with --port; without
            # it, an absent positional clobbers the flag's value with None.
            default=argparse.SUPPRESS,
            help='Port number to listen on'
        )
        
        # Flag-based arguments (modern style)
        parser.add_argument(
            '--input', '-i',
            dest='input_db',
            help='Input database file (alternative to positional arg)'
        )
        parser.add_argument(
            '--output', '-o',
            dest='output_db',
            help='Output database file for new database'
        )
        parser.add_argument(
            '--port', '-p',
            type=int,
            default=None,
            help='Port to listen on (default: from config, 6770)'
        )
        parser.add_argument(
            '--host',
            # None, not '0.0.0.0'.  run_server applies the flag with
            # `if host:`, so a default here is indistinguishable from the
            # operator naming it -- and a config.json saying
            # "host": "127.0.0.1" was silently overridden on every launch,
            # opening a world to the network its config said to keep local.
            # The default itself lives on NetworkConfig, where it belongs.
            default=None,
            help='Host to bind to (default: 0.0.0.0)'
        )
        parser.add_argument(
            '--config', '-c',
            dest='config_file',
            help='Path to config.json file'
        )
        parser.add_argument(
            '--api',
            action='store_true',
            default=False,
            help='Enable the JSON API server (first free port from 7778 up)'
        )
        parser.add_argument(
            '--api-port',
            type=int,
            default=None,
            help='Pin the API to this exact port (fails if it is in use); '
                 'omit to auto-select the first free port from 7778 up'
        )
        parser.add_argument(
            '--api-token',
            default=None,
            help='API authentication token'
        )
        parser.add_argument(
            '--web',
            action='store_true',
            default=False,
            help='Enable the browser client: serves the web client and '
                 'accepts WebSocket players (first free port from 8888 up)'
        )
        parser.add_argument(
            '--web-port',
            type=int,
            default=None,
            help='Pin the web client to this exact port (fails if it is in '
                 'use); omit to auto-select the first free port from 8888 up'
        )
        parser.add_argument(
            '--web-origins',
            default=None,
            help='Comma-separated list of browser origins allowed to open a '
                 'WebSocket (e.g. https://play.example.com). Omit on '
                 'localhost; set it when serving the client publicly'
        )
        parser.add_argument(
            '--tls-port',
            type=int,
            default=None,
            help='Serve an additional TLS listener on this exact port. The '
                 'plain port keeps working -- telnet cannot speak TLS -- so '
                 'this is a second door to the same world. Requires '
                 '--tls-cert and --tls-key'
        )
        parser.add_argument(
            '--web-tls',
            action='store_true',
            help='Serve the browser client over HTTPS using --tls-cert and '
                 '--tls-key. A flag on the web port rather than a second '
                 'one -- and the only way the client uses an encrypted '
                 'socket, since it picks ws:// or wss:// from the page it '
                 'was served over'
        )
        parser.add_argument(
            '--tls-cert',
            default=None,
            help='PEM certificate for --tls-port, including any intermediates'
        )
        parser.add_argument(
            '--tls-key',
            default=None,
            help='PEM private key for --tls-port'
        )
        parser.add_argument(
            '--log-level',
            choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
            default='INFO',
            help='Logging level (default: INFO)'
        )
        parser.add_argument(
            '--dev',
            action='store_true',
            help='development mode: pick the lone .db here, reuse the '
                 'shared API token, publish a discovery file so tooling '
                 'can find this world, and hot-reload verbs from disk'
        )
        parser.add_argument(
            '--version', '-v',
            action='version',
            version=f'MegaMOO {SERVER_VERSION}'
        )
        
        args = parser.parse_args()

        if args.dev:
            _apply_dev_defaults(args)
        
        # Smart resolution of positional arguments
        # Patterns:
        #   megamoo.py database.db                              -> db, default host, default port
        #   megamoo.py database.db 6770                         -> db, default host, port 6770
        #   megamoo.py database.db localhost 6770               -> db, host localhost, port 6770
        #   megamoo.py database.db 192.168.1.1 6770            -> db, host 192.168.1.1, port 6770
        #   megamoo.py database.db newdb.db                     -> create newdb from database
        #   megamoo.py database.db newdb.db 6770                -> create newdb, port 6770
        
        if args.new_database:
            # Check if new_database is actually a host or port
            if args.new_database.isdigit():
                # It's a port: megamoo.py database.db 6770
                args.port = int(args.new_database)
                args.new_database = None
            elif '.' in args.new_database and not args.new_database.endswith('.db'):
                # Looks like an IP or hostname: megamoo.py database.db 192.168.1.1 6770
                args.host = args.new_database
                args.new_database = None
                # Third arg should be port
                if args.port and not isinstance(args.port, int):
                    # Port was captured as string in third positional arg
                    try:
                        args.port = int(args.port)
                    except:
                        pass
            elif args.new_database in ('localhost', '0.0.0.0', '127.0.0.1'):
                # Common hostnames: megamoo.py database.db localhost 6770
                args.host = args.new_database
                args.new_database = None
                if args.port and not isinstance(args.port, int):
                    try:
                        args.port = int(args.port)
                    except:
                        pass
        
        # Resolve positional vs flag arguments
        if args.input_db:
            args.database = args.input_db
        if args.output_db:
            args.new_database = args.output_db
        
        # Validate
        if not args.database:
            parser.error('Database file is required')

        # A game's own Python has to be importable before any verb runs.
        _add_game_package_to_path(args.database)

        return args
        
    def initialize_database(self, db_path, new_db_path=None):
        """
        Initialize or create the MOO database.
        
        Args:
            db_path (str): Path to existing database file
            new_db_path (str, optional): Path for new database if creating
            
        Returns:
            Database: Initialized database object
            
        Raises:
            FileNotFoundError: If db_path doesn't exist and new_db_path is None
            IOError: If database cannot be loaded
            
        If new_db_path is provided:
            1. Load the template database from db_path
            2. Create a new database at new_db_path
            3. Copy all objects from template
            4. Save and return new database
            
        If new_db_path is None:
            1. Load existing database from db_path
            2. Run any pending upgrade scripts
            3. Return loaded database
        """
        logger.info(f"Initializing database: {db_path}")
        
        if new_db_path:
            # Create new database from template
            logger.info(f"Creating new database: {new_db_path}")
            
            if not os.path.exists(db_path):
                raise FileNotFoundError(
                    f"Template database not found: {db_path}"
                )
            
            if os.path.exists(new_db_path):
                logger.warning(
                    f"Database {new_db_path} already exists. "
                    f"It will be overwritten."
                )
                
            # Load template
            template_db = Database(db_path, mode='readonly')
            template_db.load()
            
            # Create new database
            new_db = Database(new_db_path, mode='create')
            new_db.create_from_template(template_db)
            
            template_db.close()
            return new_db
        else:
            # Load existing database
            if not os.path.exists(db_path):
                raise FileNotFoundError(
                    f"Database not found: {db_path}. "
                    f"To create a new database, provide a second argument."
                )
                
            db = Database(db_path, mode='readwrite')
            db.load()
            return db
            
    def run(self):
        """
        Main entry point for the MegaMOO server.
        
        Process:
            1. Parse command-line arguments
            2. Initialize logging
            3. Load/create database
            4. Start async server
            
        Returns:
            int: Exit code (0 for success, non-zero for error)
        """
        try:
            # Parse arguments
            args = self.parse_arguments()
            
            # Set logging level
            logging.getLogger().setLevel(args.log_level)
            
            # Print banner
            self.print_banner()
            
            # Check if creating new database
            if args.new_database:
                logger.info(f"Creating new database from {args.database}")
                self.initialize_database(args.database, args.new_database)
                logger.info(f"Database created successfully at {args.new_database}")
                logger.info("Use this database to start the server:")
                logger.info(f"  python megamoo.py {args.new_database} {args.port}")
                return 0
            
            # Run server using the async run_server function
            logger.info(f"Starting server on {args.host}:{args.port}")
            logger.info(f"Database: {args.database}")
            
            # Serving the browser client on a public interface without
            # naming the origins allowed to open a socket is the one way
            # to get this badly wrong: the browser same-origin policy
            # does not cover WebSockets, so any page a logged-in player
            # visits could open an authenticated socket as them.
            if (args.web and not args.web_origins
                    and args.host not in (None, '127.0.0.1', 'localhost')):
                logger.warning(
                    'Web client is reachable on %s with no --web-origins '
                    'set: any page a logged-in player visits can open a '
                    'socket to this world in their name. Name the origins '
                    'you serve from.', args.host)

            # run_server handles everything from here
            run_server(args.database, args.port, args.host,
                       config_path=args.config_file,
                       api_enabled=args.api,
                       api_port=args.api_port,
                       api_token=args.api_token,
                       web_enabled=args.web,
                       web_port=args.web_port,
                       web_origins=args.web_origins,
                       tls_port=args.tls_port,
                       web_tls=args.web_tls,
                       tls_cert=args.tls_cert,
                       tls_key=args.tls_key)
            
            return 0
            
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
            return 0
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            return 1
            
    def print_banner(self):
        """Print startup banner with version and copyright info."""
        banner = f"""
╔═════════════════════════════════════════════════════════════════════════╗
║                                                                         ║
║   ███╗   ███╗███████╗ ██████╗  █████╗ ███╗   ███╗ ██████╗  ██████╗     ║
║   ████╗ ████║██╔════╝██╔════╝ ██╔══██╗████╗ ████║██╔═══██╗██╔═══██╗    ║
║   ██╔████╔██║█████╗  ██║  ███╗███████║██╔████╔██║██║   ██║██║   ██║    ║
║   ██║╚██╔╝██║██╔══╝  ██║   ██║██╔══██║██║╚██╔╝██║██║   ██║██║   ██║    ║
║   ██║ ╚═╝ ██║███████╗╚██████╔╝██║  ██║██║ ╚═╝ ██║╚██████╔╝╚██████╔╝    ║
║   ╚═╝     ╚═╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝     ╚═╝ ╚═════╝  ╚═════╝    ║
║                                                                         ║
║   MegaMOO Server - Version {SERVER_VERSION:<45}║
║   Based on LambdaMOO by Pavel Curtis                                    ║
║                                                                         ║
╚═════════════════════════════════════════════════════════════════════════╝
        """
        print(banner)


def main():
    """
    Application entry point.

    ``init`` is intercepted before argparse sees anything rather than
    being made a real subcommand.  Reshaping the whole CLI would change
    how every existing invocation is spelled -- ``megamoo world.db 6770``
    is in scripts and in muscle memory -- for no gain beyond tidiness.

    Returns:
        int: Exit code
    """
    if len(sys.argv) > 1 and sys.argv[1] == 'init':
        from .init import main as init_main
        return init_main(sys.argv[2:])

    app = MegaMOO()
    return app.run()


if __name__ == '__main__':
    sys.exit(main())
