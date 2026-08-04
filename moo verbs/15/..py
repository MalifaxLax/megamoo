"""
Repeat last command.

Usage: .

Re-executes the player's previous command.
Verb name: .
"""

cmd = pobj.last_command
if cmd:
    force(pobj, cmd)
else:
    pobj.msg("No previous command.")
