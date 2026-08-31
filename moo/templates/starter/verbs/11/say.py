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

spoken = args.replace('&', '&&')

pobj.msg('You say, "%s"' % spoken)

if pobj.location:
    pobj.location.msg_room('&S says, "%s"' % spoken, exclude=[pobj], sub=pobj)
