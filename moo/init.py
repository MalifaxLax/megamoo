"""
Create a new game.

    megamoo init mygame

The point of this command is the *boundary*.  Before it existed, building
a MegaMOO game meant editing the engine checkout -- verbs lived inside
it -- so every world was permanently a fork, and an engine fix could not
be delivered to one.  That is not a forecast: this project's own two
repositories have no shared git root commit, cannot be merged, and had
five separate changes hand-carried between them in a single day.

What ``init`` produces is a directory the builder owns::

    mygame/
        megamoo.toml         what to serve, and on which ports
        world.db             a copy of the starter world
        display_screen.txt   the splash shown before the login prompt
        verbs/               the verb tree -- the builder's, in the builder's git
        game/                game-specific Python, importable from verbs
            __init__.py

Nothing in it belongs to the engine, and the engine is never edited to
change any of it.  ``game/`` is a plain package on ``sys.path``, so a
verb writes ``from game.combat import swing`` exactly as it already
writes ``from moo.objects import MOOObject`` -- no plugin registry, no
hooks, nothing new to learn.
"""

import json
import pathlib
import shutil
import sqlite3
import sys

__all__ = ['init_game', 'template_dir']

#: Files a new game does not want carried over from the template.
_SKIP = {'__pycache__', '.DS_Store'}

GITIGNORE = """\
# The world is a build artifact of your verbs, not the source of truth --
# it holds player data and password hashes besides.  The verb tree and
# game/ are what belong in version control.
*.db
*.db-shm
*.db-wal
*.log
__pycache__/
"""

CONFIG = """\
# What to serve, and where.
#
# Run this game with:  megamoo --dev
# which picks the database below, publishes a discovery file so tooling
# can find the world, and reloads verbs as you edit them.

[game]
name = "{name}"
database = "world.db"
verbs = "verbs"

[server]
port = {port}
"""

README = """\
# {name}

A MegaMOO world.

    megamoo --dev

## Layout

| path | what it is |
| --- | --- |
| `verbs/` | the world's code, one file per verb, `verbs/<objnum>/<name>.py` |
| `game/` | game-specific Python, imported by verbs as `from game.x import y` |
| `world.db` | the live world -- objects, properties, players |
| `display_screen.txt` | the splash players see before the login prompt |

`world.db` is not in version control.  It is the running state; `verbs/`
and `game/` are the source.  Edit a verb in your editor and the running
server picks it up; edit one in-game with `@program` and the file is
written for you.
"""


def template_dir() -> pathlib.Path:
    """The starter world that ships with the engine."""
    return pathlib.Path(__file__).resolve().parent / 'templates' / 'starter'


def _copy_tree(src: pathlib.Path, dst: pathlib.Path) -> int:
    """Copy a directory, skipping caches.  Returns the file count."""
    n = 0
    for item in src.rglob('*'):
        if any(part in _SKIP for part in item.parts):
            continue
        target = dst / item.relative_to(src)
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            n += 1
    return n


def _point_at_own_verbs(db_path: pathlib.Path, verbs_dir: pathlib.Path):
    """
    Make the new world read its *own* verb tree.

    The template's ``#8.moo_verb_path`` names the engine's directory.
    Copied without this, a new game runs on the engine's verbs, edits to
    its own tree do nothing, and the first thing the builder changes
    silently fails to take effect.
    """
    con = sqlite3.connect(str(db_path))
    try:
        # json.dumps, not an f-string with quotes round it.  Property
        # values are read back with json.loads, and a Windows path --
        # C:\Users\... -- makes `"{path}"` invalid JSON, because \U is an
        # escape.  The world then fails to load the one property that
        # tells it where its own verbs are, on every machine that is not
        # this one.
        con.execute(
            "update properties set value = ? "
            "where objnum = 8 and name = 'moo_verb_path'",
            (json.dumps(str(verbs_dir)),))
        con.commit()
    finally:
        con.close()


def init_game(destination, name=None, port=6770, template=None) -> pathlib.Path:
    """
    Create a new game directory.

    Args:
        destination: Where to create it.  Must not already exist.
        name: Game name for the config and README.  Defaults to the
            directory name.
        port: Default port to record in ``megamoo.toml``.
        template: Starter world to copy.  Defaults to the shipped one.

    Returns:
        pathlib.Path: The directory created.

    Raises:
        FileExistsError: The destination exists.  Refused rather than
            merged: a half-overwritten game is worse than no game.
        FileNotFoundError: The template is missing from the install.
    """
    dest = pathlib.Path(destination).expanduser().resolve()
    if dest.exists():
        raise FileExistsError(f'{dest} already exists')

    src = pathlib.Path(template) if template else template_dir()
    if not (src / 'world.db').is_file():
        raise FileNotFoundError(
            f'no starter world at {src}; pass template= to point at one')

    name = name or dest.name
    dest.mkdir(parents=True)

    verbs = dest / 'verbs'
    copied = _copy_tree(src / 'verbs', verbs)
    shutil.copy2(src / 'world.db', dest / 'world.db')
    _point_at_own_verbs(dest / 'world.db', verbs)

    game_pkg = dest / 'game'
    game_pkg.mkdir()
    (game_pkg / '__init__.py').write_text(
        f'"""Game-specific Python for {name}.\n\n'
        f'Anything here is importable from a verb as ``from game.x import y``.\n'
        f'This is where code goes that is about *this world* rather than\n'
        f'about running any world -- combat tables, chargen data, economy\n'
        f'rules.  Putting it here instead of in the engine is what keeps\n'
        f'the engine upgradeable.\n"""\n')

    (dest / 'megamoo.toml').write_text(CONFIG.format(name=name, port=port))
    (dest / '.gitignore').write_text(GITIGNORE)
    (dest / 'README.md').write_text(README.format(name=name))

    # The splash shown before the login prompt.  Written out as a file the
    # builder owns, rather than left to the engine's built-in, because the
    # first thing anyone wants to change about a new world is its name on
    # the way in -- and that should mean editing your own world, not the
    # engine.  The server reads it from the working directory.
    from moo.login import DEFAULT_SCREEN
    (dest / 'display_screen.txt').write_text(DEFAULT_SCREEN.lstrip('\n'))

    print(f'Created {dest}')
    print(f'  {copied} verb files, a starter world, and an empty game/ package')
    print()
    print(f'  cd {dest}')
    print(f'  megamoo --dev')
    return dest


def main(argv=None) -> int:
    """``megamoo init`` entry point."""
    import argparse

    ap = argparse.ArgumentParser(
        prog='megamoo init', description='Create a new MegaMOO game.')
    ap.add_argument('destination', help='directory to create')
    ap.add_argument('--name', help='game name (default: directory name)')
    ap.add_argument('--port', type=int, default=6770,
                    help='default port to record (default: 6770)')
    ap.add_argument('--template', help='starter world to copy instead of '
                                       'the one that ships with the engine')
    args = ap.parse_args(argv)

    try:
        init_game(args.destination, name=args.name, port=args.port,
                  template=args.template)
    except (FileExistsError, FileNotFoundError) as exc:
        print(f'megamoo init: {exc}', file=sys.stderr)
        return 2
    return 0
