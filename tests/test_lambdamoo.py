"""
Tests for the LambdaMOO database reader and importer.

The fixture below is a complete, hand-written Format 4 database.  Writing
it out by hand rather than shipping a real core keeps the test independent
of any external file, and makes each awkward corner of the format explicit:
a recycled object, an inherited property list, every value type, the
``..`` escape, and a verb with a minimum-match star in its name.
"""

import pytest

from moo.lambdamoo import (
    LambdaMOOError, ObjRef, parse_string,
    TYPE_INT, TYPE_OBJ, TYPE_STR, TYPE_ERR, TYPE_LIST, TYPE_CLEAR, TYPE_FLOAT,
)
from moo.lambdamoo_import import (
    UNPORTED_MARKER, build_inert_verb, property_names_for, safe_property_name,
)


# --------------------------------------------------------------------------
# Fixture
# --------------------------------------------------------------------------

DB = "\n".join([
    "** LambdaMOO Database, Format Version 4 **",
    "4",                      # objects
    "2",                      # verb programs
    "0",                      # unused
    "1",                      # players
    "2",                      # ... player #2

    # ---- #0: two properties of its own, one verb with a min-match star ----
    "#0",
    "Root Object",
    "",                       # obsolete field
    "16",                     # flags: READ
    "2",                      # owner
    "-1", "-1", "-1",         # location, contents, next
    "-1", "-1", "-1",         # parent, child, sibling
    "1",                      # one verbdef
    "look l*ook",
    "2",                      # verb owner
    "173",                    # perms: rxd + dobj/iobj = this
    "-1",                     # prep: any
    "2",                      # two propdefs
    "title",
    "count",
    "2",                      # two propvals, matching the two names
    str(TYPE_STR), "Hello",
    "2", "5",                 # owner, perms (r + chown)
    str(TYPE_INT), "42",
    "2", "1",

    # ---- #1: child of #0, so its value list is title, count, extra -------
    "#1",
    "A Child",
    "",
    "0",
    "2",
    "0", "-1", "-1",          # located in #0
    "0", "-1", "-1",          # parent #0
    "1",
    "greet",
    "2",
    "173",
    "-1",
    "1",                      # one propdef of its own
    "extra",
    "3",                      # three propvals: inherited two, then its own
    str(TYPE_CLEAR),          # title: inherit from #0
    "2", "5",
    str(TYPE_LIST), "2",      # count: a list of two values
    str(TYPE_INT), "7",
    str(TYPE_OBJ), "0",
    "2", "5",
    str(TYPE_FLOAT), "3.5",   # extra
    "2", "5",

    # ---- #2: a player ----------------------------------------------------
    "#2",
    "Wizard",
    "",
    "5",                      # flags: USER | WIZARD
    "2",
    "-1", "-1", "-1",
    "0", "-1", "-1",
    "0",                      # no verbs
    "0",                      # no propdefs
    "2",                      # inherits title, count from #0
    str(TYPE_ERR), "3",       # title: E_PERM, as a value
    "2", "5",
    str(TYPE_CLEAR),
    "2", "5",

    # ---- #3: recycled ----------------------------------------------------
    "#3 recycled",

    # ---- verb programs ---------------------------------------------------
    "#0:0",
    '"the look verb";',
    "..",                     # an escaped line that is really just "."
    "player:tell(\"hi\");",
    ".",
    "#1:0",
    "x = 1;",
    ".",
    "",
])


@pytest.fixture
def db():
    return parse_string(DB)


# --------------------------------------------------------------------------
# Header and shape
# --------------------------------------------------------------------------

def test_reads_the_header(db):
    assert db.version == 4
    assert db.declared_objects == 4
    assert db.declared_verbs == 2
    assert db.players == [2]


def test_counts_objects_and_skips_recycled(db):
    assert len(db.objects) == 4
    assert len(db.live_objects) == 3
    assert db.objects[3].recycled is True


def test_no_warnings_on_a_clean_database(db):
    assert db.warnings == []


def test_rejects_a_file_that_is_not_a_database():
    with pytest.raises(LambdaMOOError, match='not a LambdaMOO database'):
        parse_string("hello\n1\n")


def test_rejects_an_unsupported_format_version():
    with pytest.raises(LambdaMOOError, match='not supported'):
        parse_string("** LambdaMOO Database, Format Version 17 **\n0\n0\n0\n0\n")


# --------------------------------------------------------------------------
# Objects
# --------------------------------------------------------------------------

def test_object_fields(db):
    root = db.objects[0]
    assert root.name == 'Root Object'
    assert root.owner == 2
    assert root.parent == -1
    assert root.propdefs == ['title', 'count']


def test_flags_decode(db):
    assert db.objects[2].is_player is True
    assert db.objects[2].is_wizard is True
    assert db.objects[0].is_player is False


# --------------------------------------------------------------------------
# Values
# --------------------------------------------------------------------------

def test_string_and_int_values(db):
    values = [v for (v, _o, _p) in db.objects[0].propvals]
    assert values == ['Hello', 42]


def test_clear_becomes_none(db):
    # #1.title is clear, meaning "inherit" -- which is what an absent
    # MegaMOO property already means.
    assert db.objects[1].propvals[0][0] is None


def test_list_float_and_objref(db):
    count = db.objects[1].propvals[1][0]
    assert count == [7, ObjRef(0)]
    assert isinstance(count[1], ObjRef)
    assert db.objects[1].propvals[2][0] == 3.5


def test_error_values_keep_their_names(db):
    assert db.objects[2].propvals[0][0] == 'E_PERM'


def test_objref_is_distinct_from_int(db):
    ref = db.objects[1].propvals[1][0][1]
    assert isinstance(ref, ObjRef)
    assert repr(ref) == '#0'
    # It still *is* an int, so arithmetic and lookups work.
    assert ref == 0


def test_unknown_value_type_is_an_error():
    broken = DB.replace(str(TYPE_STR) + "\nHello", "99\nHello", 1)
    with pytest.raises(LambdaMOOError, match='unknown value type'):
        parse_string(broken)


# --------------------------------------------------------------------------
# Verbs
# --------------------------------------------------------------------------

def test_verb_definitions(db):
    verb = db.objects[0].verbs[0]
    assert verb.names == 'look l*ook'
    assert verb.name_list == ['look', 'l*ook']
    assert verb.is_executable is True
    assert verb.dobj == 'this'
    assert verb.iobj == 'this'
    assert verb.prep_name == 'any'


def test_verb_code_is_attached(db):
    assert db.objects[0].verbs[0].code.startswith('"the look verb";')
    assert db.objects[1].verbs[0].code == 'x = 1;'


def test_dot_escape_is_undone(db):
    # ".." on disk is a code line that is really just "."
    lines = db.objects[0].verbs[0].code.split('\n')
    assert lines[1] == '.'
    assert lines[2] == 'player:tell("hi");'


def test_code_for_a_missing_verb_warns_rather_than_raising():
    broken = DB.replace("#1:0", "#1:9")
    parsed = parse_string(broken)
    assert any('only 1 verb' in w for w in parsed.warnings)


# --------------------------------------------------------------------------
# Property names come from the inheritance chain
# --------------------------------------------------------------------------

def test_property_names_put_the_objects_own_first(db):
    """
    LambdaMOO writes an object's own property definitions first, then its
    parent's, then on up the chain.

    This test asserted the opposite until it was checked against a real
    database, and it is worth saying how that survived: the count still
    matched, every value still had a name, and every name was simply the
    wrong one -- shifted by however many properties the ancestors define.
    LambdaCore's #0 inherits four from #1, so `$string_utils` read the
    value four slots along and resolved to "generic thing" instead of
    "string utilities".  Nothing looked broken.

    The ground truth, from LambdaCore itself: $string_utils -> #20
    "string utilities", $code_utils -> #59 "code utilities",
    $failed_match -> #-3.  All three are right under own-first and wrong
    under parent-first, which is what settled it.
    """
    child = db.objects[1]
    assert property_names_for(child, db) == ['extra', 'title', 'count']


def test_property_names_line_up_with_values(db):
    for obj in db.live_objects:
        assert len(property_names_for(obj, db)) == len(obj.propvals)


def test_property_name_walk_survives_a_parent_cycle(db):
    # A damaged database can point two objects at each other.  The walk
    # must stop rather than spin.
    db.objects[0].parent = 1
    assert property_names_for(db.objects[1], db) is not None


# --------------------------------------------------------------------------
# Name collisions
# --------------------------------------------------------------------------

def test_reserved_names_are_renamed():
    assert safe_property_name('flags') == ('moo_flags', True)
    assert safe_property_name('owner') == ('moo_owner', True)


def test_underscore_names_are_renamed():
    # These would otherwise be Python instance attributes, invisible to
    # the property system.
    assert safe_property_name('_mail_task') == ('moo_mail_task', True)
    assert safe_property_name('__core') == ('moo__core', True)


def test_ordinary_names_are_left_alone():
    assert safe_property_name('description') == ('description', False)
    assert safe_property_name('title') == ('title', False)


def test_renamed_names_are_valid_identifiers_and_not_underscore_led():
    for name in ('_x', '__y', 'flags', 'owner', 'contents'):
        stored, renamed = safe_property_name(name)
        assert renamed is True
        assert stored.isidentifier()
        assert not stored.startswith('_')


# --------------------------------------------------------------------------
# Inert verbs
# --------------------------------------------------------------------------

def test_inert_verb_is_valid_python(db):
    import ast
    body = build_inert_verb(db.objects[0].verbs[0], 0, '2026-01-01')
    ast.parse(body)             # must compile, or the verb cannot be stored


def test_inert_verb_keeps_the_source_verbatim(db):
    verb = db.objects[0].verbs[0]
    body = build_inert_verb(verb, 0, '2026-01-01')
    for line in verb.code.split('\n'):
        assert f'# {line}' in body


def test_inert_verb_is_marked_and_documented(db):
    body = build_inert_verb(db.objects[0].verbs[0], 0, '2026-01-01')
    assert UNPORTED_MARKER in body
    assert 'does not run' in body
    assert 'To port it' in body
    assert 'player:tell' in body          # the substitution table


def test_inert_verb_does_nothing_when_executed(db):
    body = build_inert_verb(db.objects[0].verbs[0], 0, '2026-01-01')
    # The only statement outside the docstring and comments is the return.
    statements = [ln for ln in body.split('\n')
                  if ln.strip() and not ln.startswith('#')]
    assert statements[-1].strip() == 'return None'


def test_inert_verb_survives_source_containing_triple_quotes():
    from moo.lambdamoo import LambdaVerbDef
    import ast
    nasty = LambdaVerbDef(names='x', owner=1, perms=173, prep=-1,
                          code='s = """oops""";\n\'\'\'also\'\'\'')
    body = build_inert_verb(nasty, 7, '2026-01-01')
    ast.parse(body)             # comments cannot be escaped out of
