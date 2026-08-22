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

Execution goes through :class:`~moo.verbs.VerbExecutor`, which is *not*
the path the server uses -- player input reaches
``MegaMOOServer.execute_command``, which resolves and execs the verb
itself.  This paragraph used to claim they were the same.

The difference is not cosmetic: ``VerbExecutor`` consults
``can_execute_verb`` and the server does not, so the harness refuses
verbs the server will happily run.  A harness that runs verbs its own way
passes while the server fails, which is worse than having no harness at
all -- so treat a green run here as evidence about the verb, not about
the server.

Two doors, and which one to use
-------------------------------
:meth:`World.run` is the unit-level door: you name the object and the
verb, and it executes.  Convenient, and structurally unable to test
anything about *matching* -- you did the matching yourself.

:meth:`World.command` is the integration door.  It takes the line a
player would type and walks the same steps ``execute_command`` walks:
parse, ``find_verb``, ``may_invoke``, namespace, ``run_guarded``,
``at_post_cmd``.  The two paths check different gates and neither
checks both -- ``run`` applies ``can_execute_verb``, ``command``
applies ``may_invoke`` and the parser -- so a verb that passes one has
not been shown to pass the other.

``command`` is the one that runs ``verb_baton.run_guarded``, which
means it is the only one under which a verb is atomic.  A verb that
writes and then raises keeps its writes under ``run``, and rolls them
back under ``command``, which is what the server does.  It also asserts
after every command that no verb transaction was left open: that
condition once froze a live database for thirty-eight hours while every
backup taken in the meantime looked perfect, because they were taken
from the connection holding the uncommitted writes.
"""

import contextlib
import pathlib
from typing import Any, List, Optional, Union

__all__ = ['world', 'World', 'RecordingPlayer', 'VerbResult',
           'Transcript', 'CommandResult', 'VerbTimeout', 'TransactionLeak']


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


class VerbTimeout(AssertionError):
    """A verb ran past the harness deadline and was abandoned.

    The production server bounds verb execution too, and neither it nor
    this can actually *stop* the thread.  What matters is that the caller
    stops waiting: a harness that calls the body inline hangs the whole
    test suite on one runaway loop.

    Deliberately a daemon thread rather than a ``ThreadPoolExecutor``.
    The obvious version -- ``pool.submit`` plus ``future.result(timeout)``
    -- times out correctly and then hangs pytest at exit, because executor
    threads are non-daemon and ``concurrent.futures`` joins them on the way
    out.  A guard that turns one hung test into a hung suite is worse than
    no guard.
    """


class TransactionLeak(AssertionError):
    """A command returned with a verb transaction still open.

    Checked after every :meth:`World.command`.  This is the condition that
    froze a live database for thirty-eight hours: writes accumulated in a
    transaction that never closed, so the ``.db`` on disk stopped advancing
    while every hourly backup looked perfect -- they were taken from the
    connection holding the uncommitted writes.  Nothing raised, and nothing
    could have caught it, because the old harness never ran the transaction
    wrapper at all.
    """


class Transcript:
    """Everything every observer was told, keyed by who was told it.

    :func:`_capture` records for one player and drops the rest, which is
    fine for a verb that only answers its caller and useless for one that
    emits to a room.  This records by objnum instead.

    It deliberately does not patch ``msg_room``.  ``msg_room`` is a native
    method that calls ``msg`` once per listener, so leaving it alone means
    the real fan-out runs -- the ``is_player`` gate, the ``exclude`` list,
    the ordering -- and the transcript shows exactly who the engine decided
    to tell.  That makes the fan-out itself testable, which matters for
    combat, where one blow speaks to the attacker, the target and the room
    in three different voices.
    """

    def __init__(self):
        self.by_obj = {}
        self.order = []

    def record(self, objnum, text):
        self.by_obj.setdefault(objnum, []).append(str(text))
        self.order.append((objnum, str(text)))

    def to(self, who):
        """Lines this object was sent.  Accepts an object or an objnum."""
        if hasattr(who, 'objnum'):
            who = who.objnum
        return list(self.by_obj.get(who, []))

    def heard(self, who):
        """Everything this object was sent, as one string."""
        return '\n'.join(self.to(who))

    def observers(self):
        """Objnums that were told anything, ascending."""
        return sorted(self.by_obj)

    def __repr__(self):
        return '<Transcript %s>' % ', '.join(
            '#%d:%d' % (o, len(v)) for o, v in sorted(self.by_obj.items()))


class CommandResult:
    """What a command did, from every seat in the room.

    Stringifies and ``in``-tests as the *actor's* view, because that is
    what most assertions want::

        assert 'You wave.' in w.command('wave')

    while :meth:`to` and :meth:`heard` reach the other observers.
    """

    def __init__(self, transcript, actor, returned=None, error=None):
        self.transcript = transcript
        self.actor = actor
        self.returned = returned
        self.error = error

    @property
    def lines(self):
        return self.transcript.to(self.actor)

    def to(self, who):
        return self.transcript.to(who)

    def heard(self, who):
        return self.transcript.heard(who)

    def __str__(self):
        return self.transcript.heard(self.actor)

    def __contains__(self, needle):
        return needle in str(self)

    def __repr__(self):
        return '<CommandResult actor=#%s %r>' % (self.actor, self.transcript)


@contextlib.contextmanager
def _capture_all(cls, transcript):
    """Record ``msg``/``notify``/``tell`` for every object, for one call.

    ``msg_room`` is left alone on purpose -- see :class:`Transcript`.
    """
    names = ('msg', 'notify', 'tell')
    saved = {n: cls.__dict__.get(n) for n in names}

    def make(_original):
        def patched(self, text='', *args, **kwargs):
            transcript.record(getattr(self, 'objnum', None), text)
            return None
        return patched

    try:
        for n in names:
            setattr(cls, n, make(saved[n]))
        yield transcript
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


    # -- the production path ---------------------------------------------

    #: Seconds before a verb is abandoned.  Short on purpose: the server
    #: allows COMMAND_TIMEOUT for a human waiting on a slow command, but a
    #: test suite wants to fail fast.  Set to None to disable.
    timeout = 5.0

    #: Assert after every command that no verb transaction leaked.
    guard_transactions = True

    _session = None

    def add_player(self, noun, location=None, parent=4):
        """Create a flagged player, for testing what bystanders hear.

        The flag is the whole point.  ``msg_room`` delivers only to objects
        whose ``is_player`` is true, so a bystander made without it stands
        in the room, is excluded from nothing, and hears none of it -- which
        looks exactly like a broken emit.
        """
        from .objects import ObjectFlags
        from .builtins import move
        obj = self.db.create_object(parent=parent, owner=0)
        obj.noun = noun
        obj.flags = int(obj.flags) | int(ObjectFlags.PLAYER)
        if location is not None:
            move(obj, location if hasattr(location, 'objnum')
                 else self.obj(location))
        return obj

    def _run_bounded(self, fn, *a, record=None, label='<verb>'):
        """Run the verb body off-thread with a deadline.

        contextvars are copied across so the verb context survives the hop,
        the way the server copies them into its pool.  See
        :class:`VerbTimeout` for why this is a daemon thread.

        On timeout this evicts the runaway through ``verb_baton.abandon``,
        exactly as the server's ``_await_verb`` does.  Skipping that step
        looks harmless and is not: the abandoned verb still holds the
        baton, so the *next* verb blocks on ``acquire()`` and every
        remaining test in the file times out behind it.  One runaway test
        becomes a hung file, which is the failure this deadline exists to
        prevent.
        """
        import contextvars
        import threading
        from . import verb_baton
        if self.timeout is None:
            return fn(*a)

        box = {}

        def runner():
            try:
                box['value'] = fn(*a)
            except BaseException as exc:        # noqa: BLE001 -- re-raised
                box['error'] = exc

        ctx = contextvars.copy_context()
        thread = threading.Thread(target=ctx.run, args=(runner,),
                                  daemon=True, name='harness-verb')
        thread.start()
        thread.join(self.timeout)
        if thread.is_alive():
            verb_baton.abandon(record, label)
            thread.join(1.0)            # let the unwind release the baton
            raise VerbTimeout(
                'verb ran past %.1fs and was abandoned' % self.timeout)
        if 'error' in box:
            raise box['error']
        return box.get('value')

    def command(self, text, player=None) -> CommandResult:
        """Run a raw command the way the server runs it.

        Walks the same steps as ``MegaMOOServer.execute_command``: parse,
        ``find_verb``, ``may_invoke``, ``build_verb_namespace``, compile,
        ``at_pre_cmd`` veto, ``run_guarded``, ``at_post_cmd`` -- so unlike
        :meth:`run` it exercises the parser, the auth gate and the
        transaction wrapper.

        Args:
            text: The line as a player would type it.
            player: Who is acting.  Defaults to the world's default player.

        Returns:
            CommandResult: The actor's view by default, every observer's on
            request.

        Raises:
            VerbTimeout: The verb outran :attr:`timeout`.
            TransactionLeak: The command returned with a transaction open.
        """
        from . import verb_baton
        from .parser import CommandParser, ParseError, may_invoke
        from .verb_context import clear_verb_context, set_verb_context
        from .verb_namespace import (build_verb_namespace, run_at_post_cmd,
                                     verb_body_vetoed)

        acting = self.obj(self.default_player if player is None else player)
        tr = Transcript()
        namespace = None
        err = None

        with _capture_all(type(acting), tr):
            try:
                parse_result = CommandParser(self.db, acting).parse(text)
            except ParseError as e:
                # ParseError is how the parser says "no such verb"; its
                # message is the line the player is shown.
                tr.record(acting.objnum, str(e))
                return CommandResult(tr, acting.objnum)

            verb_obj = self.db.get_object(parse_result.verb_obj)
            _defining, verb_def = verb_obj.find_verb(parse_result.verb, self.db)
            if verb_def is None or not may_invoke(acting, verb_def):
                # The same answer either way, deliberately: the server does
                # not let the staff command list be discovered by watching
                # which names deny you.
                tr.record(acting.objnum, 'Do what?')
                return CommandResult(tr, acting.objnum)

            namespace = build_verb_namespace(
                pobj=acting, this=verb_obj, db=self.db,
                verb_name=parse_result.verb,
                args=(parse_result.argstr or '').strip(),
                argstr=parse_result.argstr or '',
                verb_def=verb_def, parse_result=parse_result,
                injected_switches=parse_result.switches,
            )
            if not verb_def.compiled_code:
                verb_def.compile()

            token = set_verb_context(acting, self.db, depth=0)
            try:
                if not verb_body_vetoed(namespace):
                    record = verb_baton.Execution()
                    try:
                        self._run_bounded(
                            verb_baton.run_guarded,
                            verb_def.compiled_code, namespace, record,
                            record=record,
                            label='%s on #%s' % (parse_result.verb,
                                                 verb_obj.objnum))
                    except VerbTimeout:
                        raise
                    except Exception as e:
                        err = e
                if err is not None:
                    run_at_post_cmd(namespace, namespace.get('result'),
                                    error=err)
                else:
                    run_at_post_cmd(namespace, namespace.get('result'))
                result = namespace.get('result')
                if hasattr(result, 'send') and hasattr(result, '__next__'):
                    from .utils import InteractiveSession
                    self._session = InteractiveSession(
                        result, acting, db=self.db,
                        verb_owner=getattr(verb_def, 'owner', None)).start()
            finally:
                clear_verb_context(token)

        if self.guard_transactions:
            self.check_transactions(text)

        return CommandResult(tr, acting.objnum,
                             namespace.get('result') if namespace else None,
                             err)

    def check_transactions(self, what='the last command'):
        """Raise if a verb transaction is still open.

        Run after every :meth:`command` unless :attr:`guard_transactions`
        is off.  Exposed as a method so it can be called directly -- a test
        cannot easily make ``command`` leak, because ``run_guarded`` closes
        the transaction it opens, so the only honest way to exercise this is
        to hand it the condition.

        Raises:
            TransactionLeak: A deferral or an uncommitted transaction is
                still open.
        """
        if getattr(self.db, '_deferring', False):
            raise TransactionLeak('%s left a verb transaction open' % (what,))
        if self.db._conn is not None and self.db._conn.in_transaction:
            raise TransactionLeak(
                '%s returned with an uncommitted transaction' % (what,))

    @property
    def awaiting_input(self) -> bool:
        """Whether the last command left a prompt open."""
        return self._session is not None and not self._session.finished

    def reply(self, text) -> CommandResult:
        """Answer a prompt the last command left open.

        The server hands an interactive verb's generator to the player's
        *connection*.  A harness has no connection, so the session would
        never start and the prompt would hang -- which is exactly what
        happens driving a ``y/n`` confirmation over the API.  The World
        holds the session itself instead.
        """
        if not self.awaiting_input:
            raise AssertionError('nothing is waiting for input')
        acting = self.obj(self.default_player)
        tr = Transcript()
        with _capture_all(type(acting), tr):
            self._session.resume(text)
        return CommandResult(tr, acting.objnum)


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
