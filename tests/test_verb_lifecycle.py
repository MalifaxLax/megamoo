"""Unit tests for the verb-type lifecycle hooks.

``at_pre_cmd()`` runs during namespace construction (before ``parse()``)
and can veto the body; ``at_post_cmd()`` runs at the execution sites
afterwards, whatever happened.  These exercise the real verb-type
resolution path -- the classes below are resolved by dotted path, as a
verb's ``parent_type`` would be.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moo.verb_namespace import (build_verb_namespace, run_at_post_cmd,
                                verb_body_vetoed)
from moo.verb_types import MasterVerb


# --- Verb types under test (resolved by dotted path, like a real one) ------

class RecordingVerb(MasterVerb):
    """Records the order the engine calls its hooks in."""
    calls: list = []

    def at_pre_cmd(self):
        RecordingVerb.calls.append('pre')

    def parse(self):
        RecordingVerb.calls.append('parse')
        super().parse()

    def at_post_cmd(self):
        RecordingVerb.calls.append('post')


class VetoVerb(MasterVerb):
    def at_pre_cmd(self):
        return True


class BrokenPreVerb(MasterVerb):
    parsed = False

    def at_pre_cmd(self):
        raise RuntimeError('hook is broken')

    def parse(self):
        BrokenPreVerb.parsed = True
        super().parse()


class BrokenPostVerb(MasterVerb):
    def at_post_cmd(self):
        raise RuntimeError('cleanup is broken')


class OutcomeVerb(MasterVerb):
    seen: dict = {}

    def at_post_cmd(self):
        OutcomeVerb.seen = {'result': self.result, 'error': self.error,
                            'vetoed': self.vetoed}


class VetoedOutcomeVerb(VetoVerb):
    seen: dict = {}

    def at_post_cmd(self):
        VetoedOutcomeVerb.seen = {'vetoed': self.vetoed}


# --- Minimal stand-ins for the objects a namespace needs -------------------

class StubObject:
    def __init__(self, objnum=1, name='thing'):
        self.objnum = objnum
        self.name = name
        self.location = None
        self.owner = objnum
        self.contents = []


class StubDB:
    def get_object(self, objnum):
        return None


class StubVerbDef:
    def __init__(self, parent_type):
        self.parent_type = parent_type
        self.names = ['test']
        self.perms = 'rx'


def _namespace(verb_cls=None, args='sword from chest'):
    """Build a real namespace, optionally backed by a verb type."""
    pobj = StubObject(2, 'player')
    this = StubObject(3, 'room')
    pobj.location = this
    verb_def = None
    if verb_cls is not None:
        verb_def = StubVerbDef(f'{verb_cls.__module__}.{verb_cls.__qualname__}')
    return build_verb_namespace(
        pobj=pobj, this=this, db=StubDB(), verb_name='test',
        args=args, argstr=args, verb_def=verb_def,
    )


# --- Order ----------------------------------------------------------------

def test_pre_cmd_runs_before_parse():
    RecordingVerb.calls = []
    ns = _namespace(RecordingVerb)
    assert RecordingVerb.calls == ['pre', 'parse']
    run_at_post_cmd(ns, 'done')
    assert RecordingVerb.calls == ['pre', 'parse', 'post']


def test_parse_still_populates_slots_around_the_hooks():
    """The hooks must not cost the verb its parsed arguments."""
    RecordingVerb.calls = []
    ns = _namespace(RecordingVerb)
    assert ns['dobj'] == 'sword'
    assert ns['prep'] == 'from'
    assert ns['iobj'] == 'chest'


# --- Veto -----------------------------------------------------------------

def test_true_from_pre_cmd_vetoes_the_body():
    assert verb_body_vetoed(_namespace(VetoVerb)) is True


def test_plain_pre_cmd_does_not_veto():
    RecordingVerb.calls = []
    assert verb_body_vetoed(_namespace(RecordingVerb)) is False


def test_default_verb_types_never_veto():
    assert verb_body_vetoed(_namespace(MasterVerb)) is False


def test_namespace_without_a_verb_type_is_never_vetoed():
    """A command must not vanish because its type could not be built."""
    ns = _namespace(None)
    assert ns['_verb_inst'] is None
    assert verb_body_vetoed(ns) is False
    run_at_post_cmd(ns, 'done')          # and post is a no-op, not a crash


# --- Failure isolation ----------------------------------------------------

def test_broken_pre_cmd_fails_open_and_parsing_continues():
    BrokenPreVerb.parsed = False
    ns = _namespace(BrokenPreVerb)
    assert BrokenPreVerb.parsed is True
    assert verb_body_vetoed(ns) is False      # not vetoed by an accident
    assert ns['dobj'] == 'sword'              # and still parsed


def test_broken_post_cmd_does_not_escape():
    ns = _namespace(BrokenPostVerb)
    run_at_post_cmd(ns, 'done')               # must not raise


def test_broken_post_cmd_does_not_replace_the_original_error():
    """On the error path the hook must not mask what actually failed."""
    ns = _namespace(BrokenPostVerb)
    original = ValueError('the real failure')
    run_at_post_cmd(ns, error=original)       # must not raise


# --- Outcome published to the hook ----------------------------------------

def test_post_cmd_sees_the_return_value():
    OutcomeVerb.seen = {}
    run_at_post_cmd(_namespace(OutcomeVerb), 'the result')
    assert OutcomeVerb.seen == {'result': 'the result', 'error': None,
                                'vetoed': False}


def test_post_cmd_sees_the_exception():
    OutcomeVerb.seen = {}
    boom = RuntimeError('verb blew up')
    run_at_post_cmd(_namespace(OutcomeVerb), error=boom)
    assert OutcomeVerb.seen['error'] is boom
    assert OutcomeVerb.seen['result'] is None


def test_post_cmd_sees_that_it_was_vetoed():
    VetoedOutcomeVerb.seen = {}
    ns = _namespace(VetoedOutcomeVerb)
    assert verb_body_vetoed(ns) is True
    run_at_post_cmd(ns)
    assert VetoedOutcomeVerb.seen == {'vetoed': True}
