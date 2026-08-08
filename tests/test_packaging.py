"""
The engine is a package, not a directory you copy.

Without this, using MegaMOO means forking it: `moo verbs/` lives inside
the engine checkout, so a builder edits the engine to build a game, and
every world ends up permanently on its own branch.  `megamoo` and
`sfdev` already have no shared git root commit, which is what that looks
like once it has happened -- the two cannot be merged at all, and five
separate changes had to be hand-carried between them in a single day.
"""

import pathlib
import subprocess
import sys

import tomllib


ROOT = pathlib.Path(__file__).resolve().parent.parent


def _pyproject():
    with open(ROOT / 'pyproject.toml', 'rb') as f:
        return tomllib.load(f)


def test_the_project_is_packaged():
    assert (ROOT / 'pyproject.toml').is_file()


def test_there_is_a_console_entry_point():
    cfg = _pyproject()
    assert cfg['project']['scripts']['megamoo'] == 'moo.cli:main'


def test_the_engine_ships_without_a_game_attached():
    """
    Only `moo` is packaged.

    Shipping `moo verbs/` or `mm.db` as package data would put the engine
    and a world back in the same directory, which is the condition this
    packaging exists to end.  They become `megamoo init` templates.
    """
    packages = _pyproject()['tool']['setuptools']['packages']
    assert packages == ['moo', 'moo.web']
    assert not any(p.startswith('moo verbs') for p in packages)


def test_no_third_party_dependencies():
    # Load-bearing, not a boast: a world installs anywhere Python runs,
    # with no build toolchain and nothing to compile.
    assert _pyproject()['project']['dependencies'] == []


def test_the_engine_imports_without_being_the_working_directory():
    """
    The test that Phase 1 actually happened.

    Every helper script written against this engine used to open with
    sys.path.insert(0, '/Users/.../megamoo'), because `moo` was only
    importable from the checkout.  Run from elsewhere, with PYTHONPATH
    cleared, it must simply import.
    """
    out = subprocess.run(
        [sys.executable, '-c', 'import moo, moo.cli; print(moo.cli.main.__name__)'],
        cwd='/tmp', capture_output=True, text=True,
        env={'PATH': '/usr/bin:/bin'},
    )
    assert out.returncode == 0, out.stderr
    assert 'main' in out.stdout
