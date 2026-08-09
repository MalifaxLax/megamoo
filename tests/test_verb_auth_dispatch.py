"""The gm level a verb declares gates dispatch.

``hidden`` has always been enforced in ``find_verb``: a hidden verb is
reported as not found and cannot be typed.  ``auth`` sat beside it in the
same VerbDef and enforced nothing, while two places in the engine
documented it as though it did -- ``verb_loader`` logs "gating dispatch at
N", and ``moo_builtins.shutdown`` explains that its own guard is needed
because "the command parser's auth check does not cover a call that
arrives through call_verb".

The rule under test is ``auth_level(player) >= verb.auth`` -- what the
verb asks for, not a fixed number -- so a gm3 clears a gm3 verb, a gm4
clears it too, and a gm2 does not.
"""
from types import SimpleNamespace

import pytest

from moo.parser import CommandParser


@pytest.fixture(autouse=True)
def _bound_database(monkeypatch):
    """Bind a database so the real ``auth_level`` runs against the fakes.

    ``auth_level`` returns 0 outright when no database is bound, and it
    reaches a non-MOOObject through ``get_object`` -- so without this the
    tests would silently exercise the unbound path and every case would
    read as level 0.
    """
    class _Stub:
        def get_object(self, obj):
            return obj

    monkeypatch.setattr('moo.builtins._database', _Stub())


def _verb(auth=0, name='cmd'):
    return SimpleNamespace(names=[name], auth=auth, hidden=0)


def _parser(player_auth, verb_def):
    """A parser whose environment search always yields *verb_def*."""
    player = SimpleNamespace(objnum=42, auth=player_auth, location=None,
                             contents=[])
    p = CommandParser(database=None, player=player)
    p._search_environment = lambda name: (3, verb_def)
    return p


@pytest.mark.parametrize('player_auth,required,allowed', [
    (None,     0, True),    # open verb, ordinary character
    (['gm3'],  0, True),    # open verb, staff
    (None,     3, False),   # the regression: staff verb, ordinary character
    (['gm1'],  3, False),
    (['gm2'],  3, False),
    (['gm3'],  3, True),    # exactly the level asked for
    (['gm4'],  3, True),    # above it
    (['gm5'],  3, True),
    (['gm3'],  4, False),   # below a higher bar -- not "staff, therefore yes"
    (['gm1', 'gm4'], 3, True),   # highest level in the list wins
])
def test_level_required_is_the_verbs_own(player_auth, required, allowed):
    p = _parser(player_auth, _verb(auth=required))
    objnum, verb_def = p._find_verb('cmd')
    assert (verb_def is not None) is allowed
    if not allowed:
        # Reported as absent, not as refused -- the same answer `hidden`
        # gives, so the deniable commands are not discoverable.
        assert (objnum, verb_def) == (0, None)


def test_missing_verb_still_reports_missing():
    p = _parser(['gm4'], None)
    p._search_environment = lambda name: (0, None)
    assert p._find_verb('nosuch') == (0, None)


def test_player_with_no_auth_property_reads_as_level_zero():
    """An object with no `auth` at all is an ordinary character."""
    player = SimpleNamespace(objnum=7, location=None, contents=[])
    p = CommandParser(database=None, player=player)
    p._search_environment = lambda name: (3, _verb(auth=3))

    assert p._find_verb('cmd') == (0, None)


def test_refuses_when_the_level_cannot_be_established():
    """A staff verb is the wrong place to fail open."""
    class _Hostile:
        objnum = 9
        location = None
        contents = []

        @property
        def auth(self):
            raise RuntimeError('cannot read auth')

    p = CommandParser(database=None, player=_Hostile())
    p._search_environment = lambda name: (3, _verb(auth=3))

    assert p._find_verb('cmd') == (0, None)


def test_verbdef_without_an_auth_attribute_is_open():
    """Not every object reaching this path is a full VerbDef."""
    p = _parser(None, SimpleNamespace(names=['cmd']))

    objnum, verb_def = p._find_verb('cmd')
    assert verb_def is not None


def test_fails_closed_with_no_database_bound(monkeypatch):
    """No database means no way to read a level, so staff verbs stay shut.

    ``auth_level`` returns 0 when unbound rather than raising, so this is
    the ordinary refusal path rather than the exception one -- worth
    pinning either way, since the alternative would be a server that
    hands out staff commands while its database is being swapped.
    """
    monkeypatch.setattr('moo.builtins._database', None)
    p = _parser(['gm5'], _verb(auth=3))

    assert p._find_verb('cmd') == (0, None)


# ------------------------------------------------------------------
# The `@` path.  This is the one that made the check worth writing: a
# gate in the parser alone covered `eval` and missed `@dig`, because
# prefixed commands are resolved twice and only the second lookup counts.
# ------------------------------------------------------------------

def test_prefixed_commands_defer_to_the_server(monkeypatch):
    """A refused `@` verb comes back as a minimal result, not an error.

    `_parse_prefixed_command` does not raise when the verb is not found --
    it returns a result carrying the player as verb_obj and lets the
    server look the verb up again.  That is why `may_invoke` cannot live
    only in the parser: the server's lookup is `MOOObject.find_verb`,
    which enforces `hidden` and knows nothing about who is asking.
    """
    player = SimpleNamespace(objnum=42, auth=None, location=None, contents=[])
    p = CommandParser(database=None, player=player)
    p._search_environment = lambda name: (3, _verb(auth=3, name='@dig'))

    result = p.parse('@dig north')

    # Not an exception, and not the verb's real home -- the player.
    assert result.verb == '@dig'
    assert result.verb_obj == 42


def test_may_invoke_is_importable_by_the_server():
    """The server gates with the same function, not a second copy."""
    from moo.parser import may_invoke
    from moo.server import MegaMOOServer  # noqa: F401  -- import must not cycle

    assert may_invoke(SimpleNamespace(auth=['gm3']), _verb(auth=3)) is True
    assert may_invoke(SimpleNamespace(auth=['gm2']), _verb(auth=3)) is False
