"""
Usage: @restart[/web][/noapi] [noapi] [<message>]

Saves the database, disconnects all connected players, and restarts the
server process. Only usable by wizard-level staff (player_flag >= 5).

The restart re-executes the same command line, so every launch flag --
--dev, --web, --port, --log-level, the database -- comes back as it was.
Two exceptions, and they are not symmetric:

    --api   is normalised. The restarted process comes back with the JSON
            API enabled regardless of how it was originally started, so
            tooling reconnects without anyone remembering a flag. /noapi
            (or the bare word "noapi") opts out for this one restart.

    --web   is only ever added, never removed. /web turns the browser
            client on for the restarted process; without it the server
            serves exactly what it served before. The API is one loopback
            socket, but the web client is reachable by anything that can
            reach the host, so a restart must not switch it on for a
            server that never asked.

Note that --dev already implies both, so on a development server neither
switch changes anything.

An optional message can be provided, which is broadcast to all players
before the shutdown. Defaults to "Server restarting." if omitted.

Examples:
    @restart
    @restart Applying a hotfix, back in a moment.
    @restart/web Bringing the browser client up.
    @restart/noapi Restarting without the external API.
    @restart noapi Restarting without the external API.

Abbrev:  @restart=8
"""

# Check wizard permission (gm5 required)
if auth_level(pobj) < 5:
    pobj.msg("Permission denied.")
else:
    arg = argstr.strip()
    sw = [s.lower() for s in switches]

    # /noapi is the switch spelling; the bare leading word predates it and
    # still works, because it is what the docstring taught for a while.
    with_api = 'noapi' not in sw
    parts = arg.split(None, 1)
    if parts and parts[0].lower() == "noapi":
        with_api = False
        arg = parts[1].strip() if len(parts) > 1 else ""

    # None, not False: the default is "leave the launch flags alone".
    with_web = True if 'web' in sw else None

    # Use provided message or fall back to default
    message = arg if arg else "Server restarting."
    notes = ["with API" if with_api else "without API"]
    if with_web:
        notes.append("with web client")
    pobj.msg(f"Restarting server ({', '.join(notes)}): {message}")
    # Initiate server shutdown with restart flag.
    # Fall back gracefully on older server builds whose shutdown_server()
    # predates these keywords (e.g. before this build is loaded).
    try:
        shutdown_server(message, restart=True, with_api=with_api,
                        with_web=with_web)
    except TypeError:
        try:
            shutdown_server(message, restart=True, with_api=with_api)
        except TypeError:
            shutdown_server(message, restart=True)
