"""
Auth derived from a verb's own text.

The watcher publishes a verb at the auth level its code asks for, so a
staff verb that guards itself is not reachable by a player the moment it
lands on disk.  These lived in the LambdaMOO import tests, because that is
where the bug was found; they are engine behaviour and stayed behind when
the porting machinery moved out.
"""

import pytest

def test_auth_comes_from_the_guard():
    from moo.verb_loader import auth_level_required
    assert auth_level_required('if auth_level(pobj) < 3:\n    return') == 3


def test_a_documented_level_is_used_when_there_is_no_guard():
    """
    A verb that documents a level but forgets the guard used to be
    published at auth 0 -- runnable by anyone the moment the file landed
    on disk.  @checkpoint shipped that way for several minutes today.

    Falling back to the documented level is the lesser of the two
    failures.  It gates the command parser, though not call_verb, which is
    why the loader warns rather than treating it as equivalent.
    """
    from moo.verb_loader import auth_level_required
    assert auth_level_required('"""Auth: gm4+ (auth_level 4)"""') == 4


def test_the_guard_beats_the_docstring():
    # The guard is what actually enforces, so it wins even when the
    # documentation disagrees.
    from moo.verb_loader import auth_level_required
    code = '"""Auth: gm4+ (auth_level 4)"""\nif auth_level(pobj) < 2:\n    return'
    assert auth_level_required(code) == 2


def test_no_guard_and_no_docstring_is_zero():
    # Right for player commands and for hooks.
    from moo.verb_loader import auth_level_required
    assert auth_level_required('x = 1') == 0



def test_the_login_room_is_a_ref_not_object_fourteen(tmp_path):
    """
    LOGIN_ROOM was the constant 14, which is right for the shipped
    database and arbitrary anywhere else.

    In a world built from nothing, #14 is whatever was created
    fourteenth -- in practice a pooled blank character.  So logging in
    moved the player *into another player*, and the first command failed
    with "look_here not found on PlayerPlace (#14)".  It looked like a
    problem with the account model for most of a day.
    """
    from moo.database import Database
    from moo.object_utils import login_room

    db = Database(str(tmp_path / 'x.db'), mode='create')
    db.load()
    db._create_object_with_objnum(0, parent=0, owner=1)
    db._create_object_with_objnum(1, parent=0, owner=1)

    # Nothing declared, and no #14: better to leave a player standing
    # where they are than to move them somewhere arbitrary.
    assert login_room(db) is None

    room = db.create_object(parent=1, owner=1)
    db.get_object(0).add_property('start_room', room, owner=1, perms='rc')
    db.save_object(db.get_object(0))
    assert login_room(db).objnum == room.objnum

    # $login_room wins when a world wants an entry hall that is not
    # where new things get made.
    hall = db.create_object(parent=1, owner=1)
    db.get_object(0).add_property('login_room', hall, owner=1, perms='rc')
    db.save_object(db.get_object(0))
    assert login_room(db).objnum == hall.objnum
