"""
Reports what this server is running, and what this world says it is.

Usage: @version
       @version/server
       @version/db

Switches:
    /server - The engine build alone.
    /db     - What the world declares, and which template it came from.

Abbrev:  @version=4
Auth: gm1+ (auth_level 1)

Two different facts, and a bug report wants both. The engine build says
which MegaMOO is running; the world version says which of *your* game is
running on top of it, and the two move on completely separate schedules.
Given only one of them, "it broke after the upgrade" cannot be placed.

The login splash used to print the engine build under the ASCII art and
no longer does -- a player arriving is being greeted, and a build number
is the one thing on that screen addressed to nobody about to log in. This
is where it went, and why it is gm1 rather than higher: it is a fact
about the software, not a capability, and anyone who can be asked to file
a bug should be able to answer "which version".

See also: @port, @restart
"""
if auth_level(pobj) < 1:
    pobj.msg("Do what?")
    return

DIM = '&<245>'
OFF = '&n'

from moo.globals import SERVER_VERSION

from moo.login import _world_version

def show_server():
    pobj.msg(f"Engine:   {DIM}MegaMOO {SERVER_VERSION}{OFF}")

def show_db():
    declared = _world_version(db)
    if declared:
        pobj.msg(f"World:    {DIM}{declared}{OFF}")
    else:
        pobj.msg(f"World:    {DIM}(none declared){OFF}  "
                 f"-- set it with @set #0.version = ...")

    try:
        template = db.template_version()
    except Exception:
        template = None
    if template:
        pobj.msg(f"Template: {DIM}{template}{OFF}")
    else:
        pobj.msg(f"Template: {DIM}(unstamped){OFF}  "
                 f"-- created before megamoo init recorded it")

if 'server' in switches:
    show_server()
    return

if 'db' in switches:
    show_db()
    return

show_server()
show_db()
