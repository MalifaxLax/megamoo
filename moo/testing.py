"""
Run verbs without a server, so they can be tested like ordinary code.

Nothing here is new capability.  The engine is an importable package and a
verb is data in a database, so running one offline was always possible --
it just took thirty lines of setup that were easy to get wrong: load the
database, register it globally (forget this and ``max_object()`` quietly
answers 0 and ``valid()`` says False for everything), fake a player that
records what it was told, build a task and a context, and execute.

What was missing was a front door.  This is the front door::

    from moo.testing import world

    def test_go_is_defined_on_both_room_parents():
        w = world('test.db')
        out = w.run(100, '@vfind', 'go')
        assert '#16:go' in out
        assert '#17:go' in out

Execution goes through :class:`~moo.verbs.VerbExecutor`, the same path the
server uses.  A harness that ran verbs its own way would pass while the
server failed, which is worse than having no harness at all.
"""

import contextlib
import pathlib
from typing import Any, List, Optional, Union

__all__ = ['world', 'World', 'RecordingPlayer', 'VerbResult']


class VerbResult(str):
    """
    Everything the player was told, as one string.

    Subclasses ``str`` so the common assertion reads naturally::

        assert 'You wave.' in w.run(100, 'wave')

    while the structured forms stay available for tests that need them.

    Attributes:
        lines: What was sent, one entry per ``msg()`` call.
        returned: The verb's return value.
    """

    lines: List[str]
    returned: Any

    def __new__(cls, lines, returned=None):
        self = super().__new__(cls, '\n'.join(lines))
        self.lines = list(lines)
        self.returned = returned
        return self


class RecordingPlayer:
    """
    Collects what a player was told.

    Deliberately *not* a stand-in for the player object.  Wrapping the
    object in a proxy was the first attempt and it failed immediately:
    ``isinstance(obj, MOOObject)`` is how the engine decides whether it was
    handed an object or an object *number*, so a proxy gets passed to SQL
    as a row id.  The player stays the real player; only the output methods
    are diverted, on the class, for the length of one call.

    Attributes:
        said: What was sent, one entry per call.
    """

    def __init__(self, objnum: int):
        self.objnum = objnum
        self.said: List[str] = []

    def record(self, text=''):
        self.said.append(str(text))

    def __repr__(self):
        return f'<RecordingPlayer #{self.objnum}: {len(self.said)} lines>'


@contextlib.contextmanager
def _capture(cls, objnum, recorder):
    """
    Divert one object's output methods for the length of a call.

    Patches the *class* rather than the instance: setting an attribute on a
    MOOObject can mean writing a property to the database, which is not
    something a test harness should do to the world it is inspecting.  The
    patched methods check the object number and fall through for everybody
    else, so output from other objects still behaves normally.

    Args:
        cls: The player object's class.
        objnum: Whose output to capture.
        recorder: Where to put it.
    """
    names = ('msg', 'notify', 'msg_room', 'tell')
    # Note `cls.__dict__`, not getattr: msg is not a class attribute at all.
    # It is a *verb* on #1, reached through __getattr__ -- which Python only
    # consults when ordinary lookup fails.  So the patch has to be installed
    # whether or not something is already there, and removed rather than
    # restored when it was not.  Skipping the absent ones was the bug: msg
    # fell through to the real verb, which wants a live connection
    # (#100.account) that an offline player does not have.
    saved = {n: cls.__dict__.get(n) for n in names}

    def make(original):
        def patched(self, text='', *args, **kwargs):
            if getattr(self, 'objnum', None) == objnum:
                recorder.record(text)
                return None
            if original is None:
                return None
            return original(self, text, *args, **kwargs)
        return patched

    try:
        for n in names:
            setattr(cls, n, make(saved[n]))
        yield recorder
    finally:
        for n, original in saved.items():
            if original is None:
                try:
                    delattr(cls, n)
                except AttributeError:
                    pass
            else:
                setattr(cls, n, original)


class World:
    """
    A loaded database you can run verbs against.

    Args:
        path: Path to the ``.db`` file.
        default_player: Object number used when ``run()`` is not told who
            is acting.
    """

    def __init__(self, path: Union[str, pathlib.Path], default_player: int = 100):
        from .database import Database
        from . import builtins as _builtins

        self.path = str(pathlib.Path(path).expanduser())
        self.db = Database(self.path)
        self.db.load()
        # The engine's builtins read a module-level database.  Skipping this
        # does not raise -- max_object() returns 0 and valid() returns False
        # for every object, so the verb runs and quietly does nothing.  It
        # cost an hour once; it belongs in the constructor, not a docstring.
        _builtins.set_database(self.db)
        self.default_player = default_player

    # -- lookup ----------------------------------------------------------

    def obj(self, ref: Union[int, str]):
        """The object for an objnum or a ``'#12'``-style reference."""
        if isinstance(ref, str):
            ref = int(ref.lstrip('#'))
        return self.db.get_object(ref)

    def verbs_on(self, ref) -> List[str]:
        """Names of the verbs an object itself defines."""
        out = []
        for v in self.obj(ref).verbs:
            out.extend(v.names)
        return out

    # -- execution -------------------------------------------------------

    def run(self, this: Union[int, str], verb: str, args: str = '',
            player: Optional[Union[int, str]] = None) -> VerbResult:
        """
        Run a verb and return what the player was told.

        Args:
            this: Object to run the verb on -- what the verb sees as
                ``this``.  For a command verb inherited from a parent,
                pass the object the player would have matched.
            verb: Verb name.  Inherited verbs are found.
            args: The argument string, exactly as typed after the verb.
            player: Who is acting.  Defaults to the world's default
                player.

        Returns:
            VerbResult: The captured output, with ``.lines`` and
            ``.returned``.

        Raises:
            LookupError: The verb is not defined on that object or any of
                its ancestors -- named separately from a runtime failure,
                because "no such verb" and "the verb broke" are different
                problems and a test should not have to tell them apart
                from a traceback.
        """
        from .tasks import Task, TaskContext
        from .verbs import VerbExecutor

        target = self.obj(this)
        acting = self.obj(self.default_player if player is None else player)

        defining, verb_def = target.find_verb(verb, self.db)
        if verb_def is None:
            raise LookupError(
                f"no verb {verb!r} on #{target.objnum} or its parents")

        recorder = RecordingPlayer(acting.objnum)
        context = TaskContext(
            player=acting.objnum,
            this=target.objnum,
            caller=acting.objnum,
            verb=verb,
            args=args,
            argstr=args,
        )
        task = Task(context=context)
        executor = VerbExecutor(self.db)

        # Establish the thread-local verb context before executing.
        #
        # VerbExecutor.execute() does not do this; the server does it around
        # the call.  Without it, `pobj.msg(...)` -- which is a *verb* on #1,
        # not a Python method -- raises "no active verb context", so the
        # harness would fail on the single most common line in any verb.
        from .verb_context import set_verb_context, clear_verb_context

        token = set_verb_context(acting, self.db, 0)
        try:
            with _capture(type(acting), acting.objnum, recorder):
                returned = executor.execute(verb_def, task)
        finally:
            clear_verb_context(token)

        return VerbResult(recorder.said, returned)


def world(path: Union[str, pathlib.Path] = 'test.db',
          default_player: int = 100) -> World:
    """
    Load a database for testing.

    Args:
        path: Path to the ``.db`` file.  Relative paths resolve against
            the current directory.
        default_player: Object number to act as unless told otherwise.

    Returns:
        World: Ready to ``run()`` verbs against.
    """
    return World(path, default_player=default_player)
