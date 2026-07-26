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
            default='0.0.0.0',
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
            help='Enable the JSON API server (port 7778)'
        )
        parser.add_argument(
            '--api-port',
            type=int,
            default=None,
            help='API server port (default: 7778)'
        )
        parser.add_argument(
            '--api-token',
            default=None,
            help='API authentication token'
        )
        parser.add_argument(
            '--log-level',
            choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
            default='INFO',
            help='Logging level (default: INFO)'
        )
        parser.add_argument(
            '--version', '-v',
            action='version',
            version=f'MegaMOO {SERVER_VERSION}'
        )
        
        args = parser.parse_args()
        
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
            
            # run_server handles everything from here
            run_server(args.database, args.port, args.host,
                       config_path=args.config_file,
                       api_enabled=args.api,
                       api_port=args.api_port,
                       api_token=args.api_token)
            
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
    
    Returns:
        int: Exit code
    """
    app = MegaMOO()
    return app.run()


if __name__ == '__main__':
    sys.exit(main())
