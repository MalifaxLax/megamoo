"""
Tests for moo.testing -- running verbs without a server.

The harness exists because every real defect found in a day of verb work
was found by running the verb, and running one took thirty lines of setup
that were easy to get subtly wrong.  These tests cover the three ways that
setup was wrong before it worked, because each one failed *quietly*: the
wrong answer, not an exception.
"""

import pathlib

import pytest

from moo.testing import world, VerbResult


DB = pathlib.Path(__file__).resolve().parent.parent / 'test.db'
pytestmark = pytest.mark.skipif(not DB.exists(), reason='test.db not present')


@pytest.fixture(scope='module')
def w():
    return world(DB)


def test_a_verb_runs_and_its_output_is_captured(w):
    out = w.run(100, 'wave')
    assert 'You wave.' in out
    assert out.returned == 1


def test_result_is_a_string_and_a_line_list(w):
    out = w.run(100, 'wave')
    assert isinstance(out, VerbResult)
    assert isinstance(out, str)
    assert out.lines == ['You wave.']


def test_arguments_reach_the_verb(w):
    # @vfind splits argv itself, so this proves args -> argv survives.
    out = w.run(100, '@vfind', 'msg in #1 to #20')
    assert '#1:msg' in out
    assert '#1:msg_room' in out


def test_a_verb_inherited_from_a_parent_is_found(w):
    # @vfind is defined on #3; #100 reaches it through #4 -> #3.
    assert w.run(100, '@vfind', 'zzznomatch').lines


def test_missing_verb_raises_lookup_error_not_a_traceback(w):
    with pytest.raises(LookupError):
        w.run(100, 'definitely_not_a_verb')


def test_the_database_is_registered_with_builtins(w):
    # Forgetting this does not raise.  max_object() answers 0 and valid()
    # says False for every object, so a verb runs and quietly finds
    # nothing -- which is how it went unnoticed the first time.
    from moo import builtins
    assert builtins.max_object() > 0
    assert builtins.valid(1)


def test_output_methods_are_restored_afterwards(w):
    # Capture patches the *class*, so a leak would silently swallow output
    # from every later test in the process.
    from moo.objects import MOOObject
    before = 'msg' in MOOObject.__dict__
    w.run(100, 'wave')
    assert ('msg' in MOOObject.__dict__) == before


def test_running_a_verb_does_not_write_to_the_database(w):
    # A harness that mutates the world it inspects is worse than none.
    size = DB.stat().st_size
    mtime = DB.stat().st_mtime
    w.run(100, '@vfind', 'go')
    assert DB.stat().st_size == size
    assert DB.stat().st_mtime == mtime


def test_verbs_on_lists_only_locally_defined_verbs(w):
    # #16 defines the OOC room's movement commands; #1 does not.
    assert 'go' in w.verbs_on(16)
    assert 'go' not in w.verbs_on(1)


# --- write-through: disk is the source of truth ----------------------------

def test_program_writes_disk_before_the_database():
    """
    @program must not be able to leave the two copies disagreeing.

    It used to ask twice -- once for the verb, once for the file -- so
    answering yes then no left new code live with the old code still on
    disk, which is the exact divergence the disk-authoritative rule exists
    to prevent.  The file is now written first: if that fails, nothing is
    saved at all.
    """
    import inspect
    from moo import builtins

    src = inspect.getsource(builtins.program_verb)
    disk = src.index('write_verb_file(')
    saved = src.index('db.save_object(target)')
    assert disk < saved, 'the file must be written before the database'
    assert src.count('yield "Overwrite') + src.count('yield f"Overwrite') == 1, \
        'exactly one overwrite confirmation, covering both copies'


def test_port_writes_disk_before_the_database_too():
    """
    @port follows the same rule as @program.

    It used to write only the database, so a ported verb was live but had
    no file in the tree git tracks -- present until the next time anyone
    touched that path, and invisible to every file-based tool until then.
    """
    import inspect
    from moo import builtins

    src = inspect.getsource(builtins.port_verb)
    assert 'write_verb_file(' in src, '@port must write the file'
    assert src.index('write_verb_file(') < src.index('db.save_object(target)')


def test_both_commands_share_one_disk_write():
    """One implementation of the rule, not one per command."""
    import inspect
    from moo import builtins

    for fn in (builtins.program_verb, builtins.port_verb):
        src = inspect.getsource(fn)
        assert 'os.fsync' not in src, (
            f'{fn.__name__} has its own disk write; '
            f'it should call write_verb_file()')
