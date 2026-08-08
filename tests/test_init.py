"""
`megamoo init` — a game the builder owns, outside the engine.

The test that matters here is not that files appear.  It is that the new
world reads its *own* verb tree and can import its *own* Python, because
those two things are what previously forced every game to be a fork of
the engine.
"""

import pathlib
import sqlite3

import pytest

from moo.init import init_game, template_dir


pytestmark = pytest.mark.skipif(
    not (template_dir() / 'world.db').is_file(),
    reason='starter template not present')


@pytest.fixture
def game(tmp_path):
    return init_game(tmp_path / 'mygame')


def test_it_creates_the_expected_layout(game):
    for item in ('world.db', 'verbs', 'game/__init__.py',
                 'megamoo.toml', '.gitignore', 'README.md',
                 'display_screen.txt'):
        assert (game / item).exists(), item


def test_a_new_world_does_not_greet_players_as_somebody_elses_game(game):
    """
    The splash is the first thing anyone sees, before they have logged in.

    It used to say "Welcome to Shadowfall" -- the development world the
    engine was carved out of -- because a fresh game shipped no
    display_screen.txt and fell through to a built-in that had never been
    renamed.  Both halves are checked: the file the builder can edit
    exists, and the fallback behind it does not name the wrong game.
    """
    from moo.login import DEFAULT_SCREEN

    assert 'Shadowfall' not in DEFAULT_SCREEN
    screen = (game / 'display_screen.txt').read_text()
    assert screen.strip(), 'the splash is empty'
    assert 'Shadowfall' not in screen


def test_the_new_world_reads_its_own_verbs(game):
    """
    The single most important line in the whole command.

    The template's #8.moo_verb_path names the *engine's* directory.
    Copied unchanged, a new game would run on the engine's verbs while
    the builder edited their own tree to no effect -- a failure that
    looks like nothing happening at all.
    """
    con = sqlite3.connect(f'file:{game / "world.db"}?mode=ro', uri=True)
    stored = con.execute(
        "select value from properties "
        "where objnum=8 and name='moo_verb_path'").fetchone()[0]
    con.close()
    assert str(game / 'verbs') in stored
    assert 'megamoo' not in stored.replace(str(game), '')


def test_the_verb_tree_is_copied_not_shared(game):
    ours = sorted(p.name for p in (game / 'verbs').glob('*/*.py'))
    theirs = sorted(p.name for p in (template_dir() / 'verbs').glob('*/*.py'))
    assert ours == theirs
    assert (game / 'verbs').resolve() != (template_dir() / 'verbs').resolve()


def test_the_game_package_is_importable_shaped(game):
    # A plain package on sys.path -- `from game.x import y` -- rather than
    # a plugin registry, because verbs already import this way.
    assert (game / 'game' / '__init__.py').is_file()


def test_the_world_is_not_version_controlled(game):
    # It holds player data and password hashes, and it is a build
    # artifact of the verb tree.  verbs/ and game/ are the source.
    assert '*.db' in (game / '.gitignore').read_text()


def test_it_refuses_to_overwrite(tmp_path):
    init_game(tmp_path / 'twice')
    with pytest.raises(FileExistsError):
        init_game(tmp_path / 'twice')
