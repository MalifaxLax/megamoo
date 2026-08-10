"""
Say something to everyone in the room.

Usage: say <message>
       ' <message>

Examples:
    say Hello everyone!
    ' Hello everyone!

Everyone in the room hears it; you see your own line phrased as "You
say". To talk only to people sharing your table, use `tt`.

Aliases: '
"""

if not args:
    pobj.msg("Say what?")
    return

# The player's own words, going into a message that esub will read.
# `&` starts a substitution token, so an unescaped one lets anybody emit
# colour codes -- or a stray `&S` naming somebody else -- into a line
# attributed to them. Doubling it is how a literal ampersand survives.
spoken = args.replace('&', '&&')

pobj.msg('You say, "%s"' % spoken)

# &S is the speaker, resolved per listener, so it reads correctly for
# everyone and honours cname. exclude=[pobj] because the speaker has
# already had their own phrasing above.
if pobj.location:
    pobj.location.msg_room('&S says, "%s"' % spoken, exclude=[pobj], sub=pobj)
