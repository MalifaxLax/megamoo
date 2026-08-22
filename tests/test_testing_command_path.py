"""``World.command`` runs a verb the way the server does.

``World.run`` executes through ``VerbExecutor``.  The server does not: player
input reaches ``MegaMOOServer.execute_command``, which parses, resolves,
checks ``may_invoke`` and runs the body under ``verb_baton.run_guarded``.  The
two paths check different gates and neither checks both, so a verb shown to
work under one has not been shown to work under the other.

The gap that cost the most is the transaction wrapper.  ``run`` never takes
it, so under ``run`` a verb that writes and then raises *keeps* its writes --
the opposite of what the server does, which means a test asserting the
correct behaviour would have failed and one asserting the wrong behaviour
would have passed.

These tests pin the behaviours ``command`` exists to provide: the same output
as ``run`` where they agree, atomicity where they do not, a transcript for
every observer rather than just the actor, prompts that can be answered, a
deadline that fails one test instead of hanging the suite, and a standing
guard against the leaked verb transaction that once froze a live database.
"""
import shutil
from pathlib import Path

import pytest

from moo.builtins import move
from moo.testing import TransactionLeak, VerbTimeout, world
from moo.verbs import VerbDef

STARTER = Path(__file__).resolve().parent.parent / 'moo' / 'templates' / 'starter' / 'world.db'
ROOM = 200
WIZARD = 100


@pytest.fixture
def w(tmp_path):
    db_path = tmp_path / 'harness.db'
    shutil.copy(STARTER, db_path)
    world_ = world(str(db_path))
    world_.timeout = 2.0
    move(world_.obj(WIZARD), world_.obj(ROOM))
    yield world_
    world_.db.close()


def _verb(w, names, code, on=ROOM):
    w.obj(on).add_verb(VerbDef(names=list(names), code=code, owner=0))


def test_it_agrees_with_run_where_both_work(w):
    """Not a different implementation -- the same behaviour, reached the
    way the server reaches it."""
    assert w.command('look').lines == list(w.run(ROOM, 'look').lines)


def test_an_unknown_command_answers_like_the_server(w):
    assert 'Do what?' in w.command('flurbulate the wombat')


def test_a_verb_that_raises_is_atomic(w):
    """The difference that matters.  Under ``run`` the debit survives."""
    actor = w.obj(WIZARD)
    actor.add_property('purse', 100, 'rc')
    _verb(w, ['halftrade'], 'pobj.purse = pobj.purse - 40\n'
                            "raise ValueError('the merchant vanished')")

    with pytest.raises(Exception):
        w.run(ROOM, 'halftrade')
    assert w.obj(WIZARD).purse == 60, 'run() is expected to keep the debit'

    w.obj(WIZARD).purse = 100
    w.command('halftrade')
    assert w.obj(WIZARD).purse == 100, 'command() must roll the debit back'


def test_every_observer_gets_a_transcript(w):
    """The real msg_room fan-out runs: is_player gate, exclude, ordering."""
    room = w.obj(ROOM)
    here = w.add_player('Bystander', room)
    away = w.add_player('Faraway', w.obj(2))
    _verb(w, ['wave'], 'pobj.msg("You wave.")\n'
                       'pobj.location.msg_room(pobj.noun + " waves.", exclude=[pobj])')

    result = w.command('wave')
    assert result.to(WIZARD) == ['You wave.']
    assert result.to(here) == ['Wizard waves.']
    assert result.to(away) == [], 'a room emit must not leave the room'
    assert 'You wave.' in result, 'stringifies as the actor view'


def test_a_bystander_without_the_player_flag_hears_nothing(w):
    """Pins why add_player exists.  msg_room checks is_player, so an object
    made without the flag is present, excluded from nothing, and silent."""
    room = w.obj(ROOM)
    plain = w.db.create_object(parent=4, owner=0)
    plain.noun = 'Furniture'
    move(plain, room)
    _verb(w, ['shout'], 'pobj.location.msg_room("noise", exclude=[pobj])')

    assert w.command('shout').to(plain) == []


def test_a_prompt_can_be_answered(w):
    _verb(w, ['confirmit'], 'def _i():\n'
                            '    pobj.msg("Are you sure? (y/n)")\n'
                            '    answer = yield\n'
                            '    pobj.msg("Boom." if str(answer).strip().lower() in ("y", "yes")\n'
                            '             else "Cancelled.")\n'
                            'result = _i()')

    assert 'Are you sure? (y/n)' in w.command('confirmit')
    assert w.awaiting_input
    assert 'Boom.' in w.reply('y')
    assert not w.awaiting_input

    w.command('confirmit')
    assert 'Cancelled.' in w.reply('n')


def test_replying_with_nothing_pending_is_an_error(w):
    with pytest.raises(AssertionError):
        w.reply('y')


def test_a_runaway_verb_fails_one_test_not_the_suite(w):
    w.timeout = 0.5
    _verb(w, ['spin'], 'n = 0\nwhile True:\n    n += 1')
    with pytest.raises(VerbTimeout):
        w.command('spin')


def test_no_transaction_survives_a_command(w):
    """The standing guard, in its positive form.

    An artificial leak cannot be induced from here, and that is worth
    recording rather than working around: ``run_guarded`` wraps every verb
    body in ``_verb_txn``, which always closes, so a verb calling
    ``begin_verb_txn`` has it committed for it on the way out.  A player
    command therefore *cannot* leak a transaction.

    Which narrows where the leak that froze a live database for thirty-eight
    hours came from: not the command path.  Something that bypasses
    ``run_guarded`` -- a ticker, or ``VerbExecutor``, which takes neither the
    baton nor a transaction.

    So this asserts the invariant the guard enforces, on both the ordinary
    exit and the raising one.
    """
    actor = w.obj(WIZARD)
    actor.add_property('purse', 100, 'rc')
    _verb(w, ['fine'], 'pobj.purse = pobj.purse - 1')
    _verb(w, ['boom'], 'pobj.purse = pobj.purse - 1\nraise ValueError("no")')

    w.command('fine')
    assert not w.db._deferring
    assert not w.db._conn.in_transaction

    w.command('boom')
    assert not w.db._deferring, 'a raising verb must not leave a txn open'
    assert not w.db._conn.in_transaction


def test_the_guard_fires_when_a_transaction_is_open(w):
    """The guard itself, handed the condition it looks for.

    ``command`` cannot produce this state (see above), so the transaction is
    opened directly and the guard called directly.  Testing it through a
    command would only have tested that ``run_guarded`` tidies up.
    """
    w.check_transactions()                      # clean: must not raise

    w.db.begin_verb_txn()
    try:
        with pytest.raises(TransactionLeak):
            w.check_transactions('a deliberately leaked verb')
    finally:
        w.db.rollback_verb_txn()

    w.check_transactions()                      # clean again
