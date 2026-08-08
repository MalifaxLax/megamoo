"""
Displays a reference table of color formatting codes available for use
in MOO messages. Shows xterm 256-color foreground/background codes and
hex RGB foreground/background codes.

Usage: @color

Auth: gm1+ (auth_level 1)

Note: Color codes use the &<N> format for xterm colors and &<#RRGGBB>
for hex RGB. Background variants use 'bg' prefix (e.g. &<bg21>).
"""
if auth_level(pobj) < 1:
    pobj.msg("Do what?")
    return
pobj.msg(chr(9484) + chr(9472)*14 + chr(9516) + chr(9472)*14 + chr(9516) + chr(9472)*30 + chr(9488))
pobj.msg(chr(9474) + "    Format    " + chr(9474) + "   Example    " + chr(9474) + "         Description          " + chr(9474))
pobj.msg(chr(9500) + chr(9472)*14 + chr(9532) + chr(9472)*14 + chr(9532) + chr(9472)*30 + chr(9508))
pobj.msg(chr(9474) + " %%<N>         " + chr(9474) + " %%<196>       " + chr(9474) + " Xterm 256 foreground (0-255) " + chr(9474))
pobj.msg(chr(9500) + chr(9472)*14 + chr(9532) + chr(9472)*14 + chr(9532) + chr(9472)*30 + chr(9508))
pobj.msg(chr(9474) + " %%<bgN>       " + chr(9474) + " %%<bg21>      " + chr(9474) + " Xterm 256 background (0-255) " + chr(9474))
pobj.msg(chr(9500) + chr(9472)*14 + chr(9532) + chr(9472)*14 + chr(9532) + chr(9472)*30 + chr(9508))
pobj.msg(chr(9474) + " %%<#RRGGBB>   " + chr(9474) + " %%<#FF0000>   " + chr(9474) + " Hex RGB foreground           " + chr(9474))
pobj.msg(chr(9500) + chr(9472)*14 + chr(9532) + chr(9472)*14 + chr(9532) + chr(9472)*30 + chr(9508))
pobj.msg(chr(9474) + " %%<bg#RRGGBB> " + chr(9474) + " %%<bg#003366> " + chr(9474) + " Hex RGB background           " + chr(9474))
pobj.msg(chr(9492) + chr(9472)*14 + chr(9524) + chr(9472)*14 + chr(9524) + chr(9472)*30 + chr(9496))
