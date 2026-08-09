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

Hiding it does not work, and was tried: call_verb resolves through
find_verb, which filters hidden verbs, so `Hidden: yes` made `look`'s own
call fail and staff quietly got the ordinary view.

Auth: gm3+ (auth_level 3)
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
