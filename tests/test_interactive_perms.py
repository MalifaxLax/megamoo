"""A paused verb keeps its own permissions when it resumes.

An `@interactive` verb yields, waits for the player to type, and carries
on. The body after the yield is still that verb -- but it runs long after
the call frame recording who the verb runs as has been popped.

That began to matter the moment property writes were checked against the
verb's owner rather than the player. With nothing carrying the owner
across the pause, the second half of the verb was attributed to the
*player*, so chargen could not write to the account it exists to fill in:
it failed at the first slot with "Permission denied: cannot write
'characters'". Only there, too -- everything before the first yield was
fine, which made an engine bug look like a world one.

InteractiveSession takes the owner at construction (the caller still has
the VerbDef; by resume time nothing does) and pushes a frame around each
generator step. These tests pin that down at the level it broke: what
`current_perms()` answers inside a resumed body.
"""
from types import SimpleNamespace

from moo import builtins
from moo.utils import InteractiveSession


def _player():
    """Enough of a player for InteractiveSession; it only needs an objnum."""
    return SimpleNamespace(objnum=99, owner=99, _database=None)


def _asks_who_it_is(seen):
    """A verb shaped like chargen: prompt, wait, then act."""
    def gen():
        yield "Which slot? "
        seen.append(builtins.current_perms())
    return gen()


def test_resumed_body_runs_as_the_verb_owner():
    seen = []
    session = InteractiveSession(_asks_who_it_is(seen), _player(),
                                 verb_owner=0).start()
    session.resume("1")

    assert session.error is None
    assert seen == [0], "the resumed half should run as the verb's owner"


def test_owner_survives_more_than_one_pause():
    """Chargen pauses many times: a frame per step, not one per session."""
    seen = []

    def gen():
        yield "name? "
        seen.append(builtins.current_perms())
        yield "race? "
        seen.append(builtins.current_perms())

    session = InteractiveSession(gen(), _player(), verb_owner=7).start()
    session.resume("a")
    session.resume("b")

    assert session.error is None
    assert seen == [7, 7]


def test_without_a_recorded_owner_it_falls_back_to_the_player():
    """The old behaviour, kept as the thing that must not come back.

    No recorded owner means the frame falls back to the player -- which is
    exactly why every interactive verb was refused writes its own owner
    was entitled to make.
    """
    seen = []
    session = InteractiveSession(_asks_who_it_is(seen), _player(),
                                 verb_owner=None).start()
    session.resume("1")

    assert seen == [99], "falls back to the player when no owner was recorded"


def test_the_frame_does_not_outlive_the_step():
    """Pushed per step and popped again, or the stack grows all session."""
    depth = []

    def gen():
        yield "?"
        depth.append(len(builtins._frames()))

    before = len(builtins._frames())
    session = InteractiveSession(gen(), _player(), verb_owner=0).start()
    session.resume("x")

    assert depth == [before + 1], "exactly one frame while the body runs"
    assert len(builtins._frames()) == before, "and none left behind"
