"""
Emote an action to everyone in the room.

Usage: act <action>
       emote <action>
       act's <action>
       :<action>

Examples:
    act smiles warmly.          -> Ayla smiles warmly.
    :smiles warmly.             -> Ayla smiles warmly.
    act's eyes narrow.          -> Ayla's eyes narrow.
    act The wind tugs at @.     -> The wind tugs at Ayla.

An `@` anywhere in the text is replaced by your name and nothing is
prepended -- that is how you put yourself in the middle of a sentence
rather than at the front.

Sits beside `say` on #11 rather than on #13, so you can emote anywhere
you can talk, the lobby included. It still asks do_wait, which is a
no-op for a character carrying no afflictions and is why you cannot
emote your way through being paralysed.

Aliases: emote, act's, :
"""

if not argstr:
    pobj.msg("Act how?")
    return

if call_verb(pobj, 'do_wait'):
    return

action = argstr.replace('&', '&&')
name = pobj.name

if '@' in action:
    emotestr = action.replace('@', name)
else:
    emotestr = name + ("'s " if verb == "act's" else " ") + action

pobj.msg(emotestr)
if pobj.location:
    pobj.location.msg_room(emotestr, exclude=[pobj], sub=pobj)
