"""
rlook verb on #5 (ICharacter).

Staff-level look at a character. Displays the same information as look_self
but also reveals hidden and invisible status flags. Used by staff to inspect
characters with full visibility.

Called programmatically: call_verb(char, 'rlook', args=viewer_obj)

Arguments:
    args - The viewer object (the staff member looking).

This is the staff view -- object numbers, dark objects, dark exits -- and
it carried no guard of its own, relying entirely on `look` checking
auth_level before calling it. That left it dispatchable by anybody: a gm0
could type `rlook` and get the builder's view of the room.

The guard below fixes that, and the auth value derives from it, so the
parser refuses a gm0 before the verb runs.

Hiding it is what makes it safe to take `args` on faith. It is not a
command: `look` calls it with the viewer as an *object*, and a staff
member who typed it got the raw command text instead, so `target.msg()`
failed on a str.

Hiding once broke that call, which is why the guard above was written
instead -- call_verb resolved through find_verb, and find_verb filtered
hidden verbs, so `Hidden: yes` meant "unreachable by anything". That is
no longer true: the check moved to may_invoke, which only decides
whether a *typed* command may run. See parser.py's may_invoke, whose
docstring records the move.

Auth: gm3+ (auth_level 3)

Hidden:  yes
"""

if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

target = args
this.look_self(target)
if this.hidden:
    target.msg(f'{this.name} is hidden.')
if this.invis:
    target.msg(f'{this.name} is invisible.')
return True
