"""
Reports what this server is running, and what this world says it is.

Usage: @version
       @version/server
       @version/db

Switches:
    /server - The engine build alone.
    /db     - What the world declares, and which template it came from.

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

# `_world_version`, not a fresh read of #0.
#
# It is the same function the login splash calls, so the two cannot come
# to disagree about what this world calls itself -- which is the whole
# failure mode a second implementation invites, and the reason
# `connected_players()` was collapsed into one. The leading underscore is
# a module-privacy hint, not a warning: reading $version off #0 is three
# lines, and three lines duplicated is how the disagreement starts.
from moo.login import _world_version


def show_server():
    pobj.msg(f"Engine:   {DIM}MegaMOO {SERVER_VERSION}{OFF}")


def show_db():
    # What the world calls itself. Empty is the ordinary case, not a
    # fault: a starter nobody has made into a game yet has nothing of its
    # own to declare, and saying so is more useful than echoing the
    # engine's number back as though the world had chosen it.
    declared = _world_version(db)
    if declared:
        pobj.msg(f"World:    {DIM}{declared}{OFF}")
    else:
        pobj.msg(f"World:    {DIM}(none declared){OFF}  "
                 f"-- set it with @set #0.version = ...")

    # Where it came from. A different question from the one above, and the
    # one that matters when a world is upgraded: without it, a value that
    # differs from the current starter's cannot be read, because "the
    # owner changed this" and "this is simply the older default" look
    # identical and want opposite treatment.
    #
    # None means the world predates the stamp, which is most of them.
    # Worth saying plainly rather than leaving the line out, so the answer
    # to "which template" is never silence.
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
