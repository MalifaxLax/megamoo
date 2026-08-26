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

Sits beside `say` on #15 rather than on #17, so you can emote anywhere
you can talk, the lobby included. It still asks do_wait, which is a
no-op for a character carrying no afflictions and is why you cannot
emote your way through being paralysed.

Aliases: emote, act's, :
"""

if not argstr:
    pobj.msg("Act how?")
    return

# do_wait covers unconscious, sleeping, paralyzed, the five conditions and
# roundtime, and messages the player itself.
if call_verb(pobj, 'do_wait'):
    return

# The player's own text, going into a message esub will read. `&` opens a
# substitution token, so an unescaped one lets anybody emit colour codes,
# or a stray `&S` naming somebody else, inside a line attributed to them.
action = argstr.replace('&', '&&')
name = pobj.name

if '@' in action:
    # Every occurrence, and no name prefix: the point of `@` is to place
    # yourself in the sentence rather than at the front of it.
    emotestr = action.replace('@', name)
else:
    emotestr = name + ("'s " if verb == "act's" else " ") + action

pobj.msg(emotestr)
if pobj.location:
    pobj.location.msg_room(emotestr, exclude=[pobj], sub=pobj)
