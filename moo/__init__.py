"""
MegaMOO - Python MOO Server

A complete reimplementation of LambdaMOO in Python with modern features.

Copyright (c) 2026
License: MIT
"""

__author__ = 'MegaMOO Contributors'
__license__ = 'MIT'

# Package-level exports
from .objects import MOOObject
from .database import Database
from .server import MegaMOOServer
from .parser import CommandParser
from .verbs import VerbDef

__all__ = [
    'MOOObject',
    'Database',
    'MegaMOOServer',
    'CommandParser',
    'VerbDef',
]
