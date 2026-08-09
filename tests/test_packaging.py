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
    # The engine repo must not carry a game of its own any more.
    assert not (ROOT / 'moo verbs').exists()
    assert not (ROOT / 'mm.db').exists()


def test_the_starter_template_ships():
    """`megamoo init` has to work for someone who only ran pip install."""
    data = _pyproject()['tool']['setuptools']['package-data']['moo']
    assert 'templates/starter/world.db' in data
    starter = ROOT / 'moo' / 'templates' / 'starter'
    assert (starter / 'world.db').is_file()
    assert list((starter / 'verbs').glob('*/*.py'))


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


def test_the_two_version_strings_agree():
    """
    One release, one number.

    The version is spelled twice -- PEP 440 in pyproject for the package
    index, human-readable in globals for the login banner -- and two
    places holding one fact drift.  This repository has already been
    bitten by that exact shape: a world version written by hand into the
    login art while the login screen printed a different one read from
    an in-world object.

    The two spellings are one mechanical transform, 'b' -> '-beta', so
    the beta number is always written out -- 0.11.0b0 pairs with
    0.11.0-beta0, not 0.10.0-beta.  This used to compare by stripping
    'b0', which passed for exactly one release and would have failed the
    first bump; leaving the number off is what made that necessary.
    """
    from moo.globals import SERVER_VERSION

    packaged = _pyproject()['project']['version']          # 0.10.0b1
    shown = SERVER_VERSION                                 # 0.10.0-beta1
    assert packaged.replace('b', '-beta') == shown, (
        f'pyproject says {packaged}, globals says {shown}')


def test_the_browser_client_is_inside_the_package():
    """
    The client has to live under moo/, not beside it.

    server.py resolves the static directory relative to its own file.
    While that was `parent.parent / 'web'` it meant the repo root from a
    checkout and site-packages/web from an install -- a directory no
    wheel ever contained.  So the browser client worked perfectly for
    everyone running from source and answered 404 for everyone who ran
    `pip install megamoo`, which is the harder failure to notice: the
    server starts, reports the web client listening, and lies.

    Shipped that way in 0.10.0b0, b1 and b2.
    """
    import moo
    client = pathlib.Path(moo.__file__).parent / 'web' / 'client'
    assert client.is_dir(), f'no browser client at {client}'
    for f in ('index.html', 'client.js', 'client.css', 'automap.js'):
        assert (client / f).is_file(), f'missing {f}'
    assert (client / 'vendor' / 'wasmoon' / 'glue.wasm').is_file()


def test_every_client_file_is_declared_as_package_data():
    """
    A missing package-data pattern does not fail the build.

    It produces a wheel that is short a file, and the first anyone knows
    is a browser console error.  So compare what is on disk against what
    the patterns claim, rather than trusting the patterns.
    """
    import fnmatch, moo
    root = pathlib.Path(moo.__file__).parent
    patterns = _pyproject()['tool']['setuptools']['package-data']['moo']
    for f in sorted((root / 'web' / 'client').rglob('*')):
        if not f.is_file() or '__pycache__' in f.parts:
            continue
        rel = str(f.relative_to(root))
        assert any(fnmatch.fnmatch(rel, p) for p in patterns), (
            f'{rel} is in the tree but no package-data pattern ships it')
