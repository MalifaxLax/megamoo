#!/usr/bin/env python3
"""
Run a MegaMOO world.

The implementation lives in :mod:`moo.cli` so that it ships inside the
package and can be reached as the ``megamoo`` console command from any
directory.  This file stays because ``python3 megamoo.py world.db`` is in
a lot of scripts, notes and muscle memory, and breaking that to gain a
packaged entry point would be a poor trade.
"""

import sys

from moo.cli import main

if __name__ == '__main__':
    sys.exit(main())
