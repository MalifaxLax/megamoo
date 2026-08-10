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


def test_no_config_field_is_read_by_nobody():
    """
    A setting that nothing consumes is worse than a missing feature: it
    answers "is this on?" with yes.  ssl_enabled did exactly that --
    documented as requiring TLS, validated at startup so a missing
    certificate stopped the server, and read by no code at all.  Fifteen
    more were found the same way.

    So: every field on every config section must appear somewhere in the
    engine outside config.py's own declaration, docstring and
    serialisation.  Adding a knob now means wiring it up in the same
    change, or the suite says so.
    """
    import re
    from moo.config import ServerConfig

    root = pathlib.Path(__file__).resolve().parent.parent / 'moo'
    sources = {f: f.read_text() for f in root.rglob('*.py')
               if '__pycache__' not in str(f) and f.name != 'config.py'}
    config_src = (root / 'config.py').read_text()

    cfg = ServerConfig()
    sections = {'network': cfg.network, 'database': cfg.database,
                'protocol': cfg.protocol, 'api': cfg.api, 'dev': cfg.dev}
    dead = []
    for section_name, section in sections.items():
        for field_name in vars(section):
            if field_name.startswith('_'):
                continue
            if any(re.search(rf'\b{re.escape(field_name)}\b', s)
                   for s in sources.values()):
                continue
            # A field may also be consumed inside config.py itself, but
            # only outside its declaration/docstring/to_dict lines.
            real = [l for l in config_src.splitlines()
                    if field_name in l
                    and not l.strip().startswith((field_name, f"'{field_name}'",
                                                  f'{field_name} (', '#'))
                    and f"'{field_name}':" not in l]
            if not real:
                dead.append(f'{section_name}.{field_name}')
    assert not dead, 'config fields nothing reads: ' + ', '.join(dead)


def test_no_shipped_message_uses_the_retired_sigil():
    """
    The substitution sigil moved from '%' to '&'.  A message left in the
    old spelling does not fail -- it is simply shown to the player
    verbatim, and because '%' is also the display escape it arrives
    doubled: #20.osuccess read "%%S %%OMODE out." and every room watching
    somebody leave saw exactly that.

    The actor never sees osuccess or odrop, so this can survive any
    amount of solo testing.  It took two players in one room to notice.
    """
    import re
    import sqlite3

    world = (pathlib.Path(__file__).resolve().parent.parent
             / 'moo' / 'templates' / 'starter' / 'world.db')
    if not world.is_file():
        import pytest
        pytest.skip('starter world not present')
    db = sqlite3.connect(f'file:{world}?mode=ro', uri=True)
    token = re.compile(r'%(S|s|D|d|I|i|N|MODE|OMODE|ps|po|pp|pr)\b')
    bad = [f'#{o}.{n} = {v[:40]}'
           for o, n, v in db.execute('select objnum,name,value from properties')
           if v and token.search(v)]
    assert not bad, 'properties still written in the old sigil: ' + '; '.join(bad)


def test_nothing_stores_a_capitalised_name():
    """
    There is no cname property, and nothing may reintroduce one.

    It held a second copy of `name` with the first letter raised.  Being
    inheritable, an object that never set its own answered with its
    *prototype's*, so a character with a perfectly good name was
    announced to the room as "ICharacter walks in from the west" -- and
    the actor never sees a third-person emit, so a world can be built for
    hours before anyone notices.  Backfilling every character was the
    treatment, not the cure: the next object made without one was wrong
    again.

    &S/&D/&I capitalise `name` themselves, and verb code that needs it
    calls su.capitalise(obj.name).  Measured before removing it: of 123
    values in the starter world 0 differed from capitalising name; of 405
    in Shadowfall 3 differed, and all three were *un*capitalised -- wrong
    rather than deliberate.
    """
    import sqlite3

    root = pathlib.Path(__file__).resolve().parent.parent
    verbs = root / 'moo' / 'templates' / 'starter' / 'verbs'
    world = root / 'moo' / 'templates' / 'starter' / 'world.db'
    if not verbs.is_dir() or not world.is_file():
        import pytest
        pytest.skip('starter template not present')

    # Prose may still explain why it is gone; code may not name it.  An
    # attribute catches `obj.cname`, a bare 'cname' constant catches it
    # spelled as a property name -- add_property, a skip list -- while
    # leaving the docstrings that record the reason alone.
    import ast

    offenders = []
    for f in sorted(verbs.rglob('*.py')):
        for node in ast.walk(ast.parse(f.read_text())):
            hit = (isinstance(node, ast.Attribute) and node.attr == 'cname') or \
                  (isinstance(node, ast.Constant) and node.value == 'cname')
            if hit:
                offenders.append(f'{f.relative_to(verbs)}:{node.lineno}')
    assert not offenders, 'starter verbs still name cname in code: ' + ', '.join(offenders)

    db = sqlite3.connect(f'file:{world}?mode=ro', uri=True)
    rows = db.execute("select count(*) from properties where name='cname'").fetchone()[0]
    assert rows == 0, f'{rows} cname properties still in the shipped world'
