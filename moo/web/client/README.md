# MegaMOO web client

A browser client for MegaMOO: a MUD terminal, a corner map of the world,
and a user scripting system with two sandboxed language hosts.

Served by the game server itself — one port covers the static files and
the WebSocket, so there is no separate web server and no build step.

```bash
python megamoo.py sf.db --web
```

`--web` takes the first free port from 8888 up; `--web-port N` pins one
exactly. Open `http://<host>:<port>/`.

For a public deployment, name the origins allowed to open a socket:

```bash
python megamoo.py sf.db --web --web-origins https://play.example.com
```

Without that, any page a logged-in player visits can open an
authenticated socket to the game in their name — the browser same-origin
policy does not cover WebSockets. Behind a TLS-terminating proxy the
client picks `wss://` automatically from the page's own scheme.

## Files

| File | Role |
| --- | --- |
| `index.html` | Page structure |
| `client.css` | All styling, plus the colour classes `moo/web/color.py` emits |
| `client.js` | Socket, scrollback, input line, event bus, public API |
| `commands.js` | The `\` client commands: aliases, triggers, speech |
| `automap.js` | Corner map of the world, built from `Room.Info` |
| `inventory.js` | Corner inventory panel, built from `Char.Inventory` |
| `panels.js` | Renders script-declared UI from a widget vocabulary |
| `scripting.js` | Script manager, host registry, the API scripts call |
| `scripts-ui.js` | Script manager dialog |
| `hosts/js-worker.js` | JavaScript host (Web Worker) |
| `hosts/lua.js` | Lua host (wasmoon) |
| `vendor/wasmoon/` | Lua 5.4 compiled to WebAssembly (MIT) |

## Wire protocol

Server to client:

```json
{"type": "text",   "data": "<html>"}
{"type": "prompt", "data": "> "}
{"type": "echo",   "enabled": false}
{"type": "gmcp",   "package": "Room.Info", "data": {}}
```

Client to server:

```json
{"type": "input", "data": "look"}
{"type": "gmcp",  "package": "...", "data": {}}
```

`text` arrives as HTML because `moo/web/color.py` has already turned MOO
`%` codes and ANSI escapes into spans, escaping everything else. That
module is the only producer of markup the client renders.

`echo` is the WebSocket stand-in for telnet's `IAC WILL ECHO`: the server
sends `enabled: false` ahead of a password prompt and the client masks
the next line.

## Out-of-band data

Every GMCP package the server sends is republished on the client's event
bus, whether or not the client knows what it means:

```js
MegaMOO.on('gmcp', ({package, data}) => { ... });   // all packages
MegaMOO.on('gmcp:Room.Info', (data) => { ... });    // one package
```

A new server-side package therefore needs no client change to become
scriptable. The package sent today is `Room.Info`.

```json
{"num": 13, "name": "Upstairs - Nexus", "desc": "...",
 "exits": ["north", "south"], "coords": [0, 1, 0]}
```

## Staleness

The client reconnects its WebSocket on its own when the server restarts,
**without reloading the page**. That is right for a dropped connection,
but it means a player can keep running JavaScript from before a deploy
indefinitely — and a stale client misbehaving looks exactly like a server
bug.

`GET /build` returns the newest mtime across `web/`. The page reads it on
load and on every reconnect, and prints a notice when it changes.

Rule of thumb:

- Changed something in `web/` → reload the page
- Changed something in `moo/` → restart the server *and* reload the page

## Map

The corner map covers **in-character rooms only**. `Room.Info` carries
`ic`, which is `is_icroom` — defined `True` on `#17 ICRoom` and inherited
by every IC room. OOC rooms (the entry hall, chargen) are never recorded
and the panel hides while you are in one.

Passing through an OOC room also breaks the trail, so walking IC → OOC →
IC does not invent a link between two rooms that aren't connected. A map
stored before this rule existed drops its OOC rooms the next time it
loads.

A server that doesn't send `ic` gets no map at all — the client will not
guess.

The map is drawn from `Room.Info`. `coords` is the room's cell in
a canonical layout that `moo/roommap.py` derives once from the exit
graph — a breadth-first walk of every room's `dexits`, one cell per
compass direction and one level per `u`/`d`. Because the layout is
computed from the world rather than from the route a player walked, every
client draws the world the same way, loops close correctly, and up/down
becomes a real level rather than a badge.

Two rules keep non-euclidean geography from wrecking the walk: a room
already placed keeps its position (a loop that doesn't close just gets a
longer connecting line), and a room whose cell is taken is moved to the
nearest free one. Disconnected regions are laid out side by side.

The walk alone is not enough, because whichever exit reaches a room first
decides its cell. A market square also reachable from the street outside
can be claimed by the street and end up outside the block it belongs to,
dragging all its other exits out of alignment. So a relaxation pass then
offers every room the cells its neighbours imply and moves it when one
satisfies more of its exits — **including swapping** with whatever sits
there, since a grid cannot embed a non-planar graph and two areas joined
by a long path can overlap, leaving an unrelated room parked in the
middle of somewhere else. Neither can move while the other holds the
cell.

On the shipped world this takes exit-alignment from 81% to 96% (the
remainder being genuinely non-euclidean links), with no two rooms ever
sharing a cell.

Only the coordinate of the room the player is *in* is ever sent. Exit
destinations are deliberately withheld even though `dexits` has them —
sending those would hand players the topology of rooms they have never
visited. Unwalked exits therefore render as short stubs, a visible
frontier rather than a spoiler.

The layout is computed lazily on first use and cached, so **a server that
gains or re-links rooms mid-session keeps serving the old layout until it
restarts**. Call `moo.roommap.invalidate()` after building to force a
rebuild.

Links are recorded from the direction the player moved. Where that isn't
knowable from what they typed — `.` repeating the last command, a script
calling `moo.send`, an exit entered by object name — the direction is
taken from the two rooms' canonical positions instead: rooms one cell
apart are one cell apart *because* an exit joins them that way. Only
immediate neighbours count, so a teleport records the room without
inventing a corridor.

Some real connections still join rooms the grid had to place far apart.
Drawn literally those are wires cutting across unrelated parts of the
map, so a link spanning more than three cells becomes a short stub at
each end instead — the connection still reads, without the clutter.

If a server sends no `coords`, the client falls back to placing rooms by
the direction the player moved.

## Client commands

A line starting with `\` is the client's own and never reaches the game.
The set follows MegaTerm's, so muscle memory carries between the two.

| Command | Does |
| --- | --- |
| `\connect [wsUrl]` | Reconnect. A URL re-points the socket, **this origin only** |
| `\disconnect` | Close the socket and stay closed |
| `\quit` | Disconnect — a browser tab cannot close itself |
| `\clear` | Empty the scrollback |
| `\alias [name] [value...]` | Set, show, or list aliases |
| `\unalias <name>` | Remove one |
| `\trigger <sub> ...` | `add`, `remove`, `enable`, `disable`, `list`, `test` |
| `\speech` | Toggle text-to-speech over the output |
| `\su` / `\sd` / `\se` | Scroll up / down / to the end |
| `\test [ansi\|plain]` | Fill the scrollback, to look at colour and scrolling |
| `\help` | The above |

Aliases expand the **first word only** — `k orc` with `k = kill` sends
`kill orc`. Both aliases and triggers live in `localStorage` and save as
you set them, which is why there is no `\save`.

### Triggers

```
\trigger add <name> text <pattern> <action> [value]
\trigger add <name> gmcp <package> send <command>
```

Patterns are regular expressions; quote one containing spaces. The
actions are `send <command>`, `highlight <style>`, and `gag`. Styles are
a fixed set — `yellow red green cyan blue magenta grey` — rendered as
translucent backgrounds rather than text colours, because game text
arrives already wrapped in its own colour spans and those win over any
foreground set on an ancestor.

`gag` and `highlight` are why `term.write` buffers output by line: a
filter that can suppress a line has to run *before* that line is in the
document. Composed blocks — the splash, a full-screen frame, an image —
are exempt, since gagging one row of ASCII art would only wreck the
drawing it belongs to. A gagged line is still published on the `line`
event, so scripts see the whole stream either way.

`\connect` refuses a cross-origin URL on purpose. Everything arriving on
the socket is trusted *as markup* by the terminal, which is safe only
because the server at the other end is the one that escaped it; a socket
aimed elsewhere is script execution on this page and a convincing fake
password prompt. The legitimate cross-origin case — page on a CDN, game
elsewhere — is configured once in `?ws=` at load, where it is the
deployment's decision rather than a typed one.

## Scripting

Scripts are written in **Lua** or **JavaScript** and managed from the
*Scripts* button. Both languages get an identical API, so logic ports
between them.

Scripts get their own regex triggers and aliases through `moo.trigger`
and `moo.alias`; those are independent of the `\` commands above, and
run after them — `commands.js` attaches first, so a script's alias
pattern cannot swallow `\help`.

### Choosing a language

|  | JavaScript | Lua |
| --- | --- | --- |
| Sandbox | Web Worker with `fetch`, `WebSocket`, `XMLHttpRequest`, `importScripts`, `indexedDB` and `Worker` removed | A Lua VM with no JS bridge; `io`, `package`, `require`, `load` and `debug` removed |
| Isolation | A **blocklist** — correct as far as it goes, but a maintained list | A property of the interpreter: the VM only has what it was handed |
| Cost | Nothing | ~420 KB, loaded lazily on first use |
| Debugging | Browser devtools | Errors reported with a Lua traceback |

Use JavaScript for your own scripts. Use **Lua for anything someone else
wrote** — a hostile JS script that finds a reference the blocklist missed
runs as you, in your session.

### API

Lua uses `snake_case`, JavaScript `camelCase`; they are otherwise the
same. JavaScript calls return promises.

| Call | Does |
| --- | --- |
| `moo.echo(text)` | Write a line to the scrollback |
| `moo.send(command)` | Send a command as if typed |
| `moo.send_gmcp(pkg, data)` | Send a client-to-server GMCP package |
| `moo.connected()` | Whether the socket is open |
| `moo.on(event, fn)` | Subscribe to a client event |
| `moo.trigger(pattern, fn)` | Run `fn` on matching output lines |
| `moo.alias(pattern, fn)` | Claim matching input before it is sent |
| `moo.timer(ms, fn)` | Repeating timer; returns a handle |
| `moo.cancel_timer(handle)` | Stop a timer |
| `moo.storage.get/set(key, value)` | Persistent, per-script storage |
| `moo.panel(id, spec)` | Declare or update a UI panel |
| `moo.remove_panel(id)` | Remove a panel |

Events: `connect`, `disconnect`, `prompt`, `gmcp`, `gmcp:<Package>`.

Patterns are literal substrings by default. Pass `{regex = true}` (Lua)
or a `RegExp` (JavaScript) for a regular expression; capture groups are
passed to the handler as a second argument.

### Panels

Scripts do not produce markup. A panel is described as data and rendered
by the client, so no script — in either language — can inject HTML into
the page:

```lua
moo.panel('vitals', {
  title = 'Vitals',
  body = {
    type = 'stack',
    children = {
      {type = 'text',  text = 'Zarquon', strong = true},
      {type = 'bar',   label = 'FTG', value = 96, max = 410, color = 'accent'},
      {type = 'gauge', label = 'Score', value = 1200},
      {type = 'table', head = {'Foe', 'Score'}, rows = {{'Morloth', 900}}},
    },
  },
})
```

Widgets: `text` (`muted`, `strong`, `color`), `bar` (`label`, `value`,
`max`, `color`), `gauge`, `row`, `stack`, `table`, `space`. `color` is a
name from a fixed set — `default`, `muted`, `faint`, `accent`, `own`,
`foe`, `neutral` — never a raw CSS value.

### Example

```lua
-- Announce each new room and keep a location panel updated.
moo.on('gmcp:Room.Info', function(room)
  moo.panel('where', {title = 'Location', body = {
    type = 'stack',
    children = {
      {type = 'text', text = room.name, strong = true},
      {type = 'text', text = 'exits: ' .. tostring(#room.exits), muted = true},
    },
  }})
  moo.storage.set('lastRoom', room.name)
end)

moo.trigger('a guard', function(line) moo.echo('*** guard here ***') end)
moo.alias('^h$', function() moo.send('go north') end, {regex = true})
```
