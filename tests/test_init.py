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

    The template's ``moo_verb_path`` names the *engine's* directory.
    Copied unchanged, a new game would run on the engine's verbs while
    the builder edited their own tree to no effect -- a failure that
    looks like nothing happening at all.

    Asked without naming an object number.  This test used to say
    ``objnum = 8``, which stopped being the Body Bag when the starter
    adopted sf's numbering, and a `fetchone()[0]` on no rows is a
    TypeError rather than an answer.  There is exactly one holder, so
    finding it by the property is both simpler and durable.
    """
    con = sqlite3.connect(f'file:{game / "world.db"}?mode=ro', uri=True)
    rows = con.execute(
        "select objnum, value from properties "
        "where name = 'moo_verb_path'").fetchall()
    con.close()
    assert len(rows) == 1, f'expected one moo_verb_path holder, found {rows}'
    stored = rows[0][1]
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


def test_the_world_records_which_template_it_came_from(game):
    """A new world says which release's template it is a copy of.

    Nothing else records it. ``version`` in the metadata is the schema's,
    and the world is a byte copy of the template, so ``created`` is the
    *template's* creation time and is identical in every world ever made
    from it.

    It matters for upgrading one later. When a value in a world differs
    from the current template's, "the owner changed this" and "this is
    the older default" look identical and want opposite treatment.
    Knowing the starting point makes that a three-way comparison rather
    than a guess.
    """
    from moo.database import Database
    from moo.globals import SERVER_VERSION

    db = Database(game / 'world.db', mode='readonly')
    db.load()
    try:
        assert db.template_version() == SERVER_VERSION
    finally:
        db.close()


def test_a_world_without_the_stamp_says_so_rather_than_guessing(tmp_path):
    """Worlds created before the stamp existed report None, not a version.

    They can still be upgraded additively -- a new prototype lands in the
    reserved number range, a new verb or property is simply absent -- but
    a *changed* value cannot be judged, and answering None is what lets a
    tool know that.
    """
    import sqlite3
    from moo.database import Database

    game = init_game(tmp_path / 'unstamped')
    conn = sqlite3.connect(game / 'world.db')
    conn.execute("DELETE FROM metadata WHERE key = 'template_version'")
    conn.commit()
    conn.close()

    db = Database(game / 'world.db', mode='readonly')
    db.load()
    try:
        assert db.template_version() is None
    finally:
        db.close()
