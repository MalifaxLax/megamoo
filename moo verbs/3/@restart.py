"""
Usage: @restart [noapi] [<message>]

Saves the database, disconnects all connected players, and restarts the
server process. Only usable by wizard-level staff (player_flag >= 5).

By default the restarted process comes back with the JSON API enabled
(equivalent to launching with --api), regardless of how the server was
originally started. Prefix the command with the word "noapi" to restart
without the API for this one restart.

An optional message can be provided, which is broadcast to all players
before the shutdown. Defaults to "Server restarting." if omitted.

Examples:
    @restart
    @restart Applying a hotfix, back in a moment.
    @restart noapi Restarting without the external API.
"""

# Check wizard permission (gm5 required)
if auth_level(pobj) < 5:
    pobj.msg("Permission denied.")
else:
    # Optional leading "noapi" token opts out of (re-)enabling the API.
    arg = argstr.strip()
    with_api = True
    parts = arg.split(None, 1)
    if parts and parts[0].lower() == "noapi":
        with_api = False
        arg = parts[1].strip() if len(parts) > 1 else ""

    # Use provided message or fall back to default
    message = arg if arg else "Server restarting."
    api_note = "with API" if with_api else "without API"
    pobj.msg(f"Restarting server ({api_note}): {message}")
    # Initiate server shutdown with restart flag.
    # Fall back gracefully on older server builds whose shutdown_server()
    # predates the with_api keyword (e.g. before this build is loaded).
    try:
        shutdown_server(message, restart=True, with_api=with_api)
    except TypeError:
        shutdown_server(message, restart=True)
