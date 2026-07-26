"""
rlook verb on #5 (ICharacter).

Staff-level look at a character. Displays the same information as look_self
but also reveals hidden and invisible status flags. Used by staff to inspect
characters with full visibility.

Called programmatically: call_verb(char, 'rlook', args=viewer_obj)

Arguments:
    args - The viewer object (the staff member looking).
"""

target = args
this.look_self(target)
if this.hidden:
    target.msg(f'{this.name} is hidden.')
if this.invis:
    target.msg(f'{this.name} is invisible.')
return True
