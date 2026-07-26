"""
Usage: @shutdown [<message>]

Saves the database, unpuppets all characters, and shuts the server down.
An optional message is broadcast to all players before disconnect.
Requires confirmation before proceeding.

Examples:
    @shutdown
    @shutdown Server going down for maintenance.
"""
if auth_level(pobj) < 5:
    pobj.msg("Do what?")
    return

message = argstr.strip() if argstr.strip() else "Server shutting down."

pobj.msg(f"Shutdown message: {message}")
pobj.msg("Are you sure you want to shut down the server? (y/n)")
answer = yield ""
if answer.strip().lower() != 'y':
    pobj.msg("Shutdown aborted.")
    return

pobj.msg("Shutting down...")
shutdown_server(message)
