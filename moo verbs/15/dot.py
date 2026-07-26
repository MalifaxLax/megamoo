"""
Repeat last command.

Usage: .

Re-executes the player's previous command.
Verb name: .
"""

cmd = getattr(pobj, 'last_command', None)
if cmd:
    force(pobj, cmd)
else:
    pobj.msg("No previous command.")
