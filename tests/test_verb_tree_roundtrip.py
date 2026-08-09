"""A world must be rebuildable from its verb tree.

The tree is what git tracks. Until verb files could describe their own
aliases, abbreviations, hidden flag and permissions, rebuilding a world
from it produced something subtly different and said nothing: ``look``
stopped answering to ``l``, two dozen direction names collapsed to ``n``,
and hidden internal hooks became commands a player could type.

These drive ``reload_verb_code`` directly, which is what both the
``@reload`` verb and the auto-reload watcher call.
"""
from types import SimpleNamespace

import pytest

from moo.verb_loader import reload_verb_code, is_blank_verb_file
from moo.verbs import VerbDef


class _Obj:
    """Enough of a MOOObject for the loader: verbs, owner, and the hooks."""

    def __init__(self, verbs=(), owner=0):
        self.verbs = list(verbs)
        self.owner = owner
        self.modified = 0
        self.invalidated = 0

    def add_verb(self, v):
        self.verbs.append(v)

    def _mark_modified(self):
        self.modified += 1

    def invalidate_inheritance_cache(self):
        self.invalidated += 1


def _file(meta_lines='', body='return 1\n'):
    return '"""\nDoes a thing.\n%s"""\n%s' % (meta_lines, body)


# ------------------------------------------------------------------
# Creating
# ------------------------------------------------------------------

def test_a_new_verb_takes_its_names_from_the_file():
    obj = _Obj()

    assert reload_verb_code(obj, '@make', _file('Aliases: @create\n')) == 'created'
    assert obj.verbs[0].names == ['@make', '@create']


def test_a_new_verb_takes_abbreviations_hidden_and_perms():
    obj = _Obj()
    reload_verb_code(obj, 'look', _file('Aliases: l\nAbbrev: look=1\n'
                                        'Hidden: yes\nPerms: rxd\n'))
    v = obj.verbs[0]

    assert v.min_lengths == {'look': 1}
    assert v.hidden is True
    assert v.perms == 'rxd'


# ------------------------------------------------------------------
# Updating -- disk wins
# ------------------------------------------------------------------

def test_disk_adds_an_alias_to_an_existing_verb():
    obj = _Obj([VerbDef(names=['@make'], code='old', owner=0)])

    assert reload_verb_code(obj, '@make', _file('Aliases: @create\n')) == 'updated'
    assert obj.verbs[0].names == ['@make', '@create']


def test_disk_removes_an_alias_it_no_longer_declares():
    """The point of disk winning: the tree is a faithful description."""
    obj = _Obj([VerbDef(names=['@make', '@create'], code='old', owner=0)])

    reload_verb_code(obj, '@make', _file())

    assert obj.verbs[0].names == ['@make']


def test_renaming_invalidates_the_resolution_cache():
    """Otherwise a new alias does not answer until something else clears it."""
    obj = _Obj([VerbDef(names=['@make'], code='old', owner=0)])

    reload_verb_code(obj, '@make', _file('Aliases: @create\n'))

    assert obj.invalidated == 1


def test_no_name_change_does_not_invalidate():
    obj = _Obj([VerbDef(names=['@make'], code='old', owner=0)])

    reload_verb_code(obj, '@make', _file())

    assert obj.invalidated == 0


def test_hidden_can_be_cleared_from_disk():
    obj = _Obj([VerbDef(names=['v'], code='old', owner=0, hidden=True)])

    reload_verb_code(obj, 'v', _file())

    assert obj.verbs[0].hidden is False


def test_auth_is_not_taken_from_metadata():
    """auth stays derived from the guard; the file does not override it.

    A verb's level is enforced by its own ``auth_level(pobj) < N`` guard,
    and the stored value is derived from that. Letting a docstring line
    set it would let the two disagree, which is the bug the derivation
    exists to prevent.
    """
    obj = _Obj([VerbDef(names=['v'], code='old', owner=0, auth=3)])

    reload_verb_code(obj, 'v', _file())

    assert obj.verbs[0].auth == 3


# ------------------------------------------------------------------
# The one thing a file cannot say
# ------------------------------------------------------------------

def test_a_blank_file_is_skipped_and_keeps_its_metadata():
    """A blank file means no opinion, not an empty verb.

    #199's `_buy` and `_cost` are deliberate empty overrides shadowing
    real implementations on #17 and #92, and #3's `_allow` is the same
    shape. The loader has always skipped these, so their hidden flag
    survives -- but it survives because nothing on disk describes them,
    which is exactly why a rebuild from a blank file cannot restore it.
    """
    obj = _Obj([VerbDef(names=['_allow'], code='\n', owner=0, hidden=True)])

    assert reload_verb_code(obj, '_allow', '\n') == 'skipped'
    assert obj.verbs[0].hidden is True


@pytest.mark.parametrize('code', ['', '\n', '   \n\n', '# just a comment\n'])
def test_what_counts_as_blank(code):
    assert is_blank_verb_file(code) is True


def test_a_docstring_alone_is_not_blank():
    """Which is how a do-nothing verb can still describe itself.

    Giving one of those empty overrides a docstring costs nothing at
    runtime -- a body that is only a docstring returns None, the same as
    a body of one newline -- and buys it somewhere to record that it is
    hidden.
    """
    assert is_blank_verb_file('"""Deliberately does nothing."""\n') is False
