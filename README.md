# MegaMOO

A modern, from-scratch text world engine in Python 3, built on the [LambdaMOO](https://en.wikipedia.org/wiki/LambdaMOO) model — a persistent, multiplayer, fully programmable text world. Around 38,000 lines of Python built on `asyncio`, with **zero third-party dependencies**: the engine runs on the standard library alone.

Where classic MOO servers make you program in a purpose-built MOO language, MegaMOO's in-world programming language is **Python itself**. Every verb — from `look` to your own game systems — is a plain Python file with the full standard library available, executed live against a persistent object database.

> **This reimplements MOO's model, not its language.** You get objects carrying their own properties and verbs, single-parent inheritance, live in-world programming, and a wizard/programmer/owner permission model. You do not get a MOO-language interpreter — existing MOO code does not run unmodified and has to be ported to Python. That port is largely mechanical; see [Porting from LambdaMOO](#porting-from-lambdamoo).

## Quick start

Requires Python 3.10+.

```bash
pip install megamoo
megamoo init mygame
cd mygame && megamoo --dev
```

Then open the URL it prints, or `telnet localhost 6770`, and you are in a
world you can build.

Also on the [releases
page](https://github.com/MalifaxLax/megamoo/releases) as a wheel, if you
would rather pin a specific build than take whatever `pip` resolves.

`megamoo --dev` picks the database in the current directory, reloads verbs
as you edit them, and publishes a discovery file so external tooling can
find the running world. What `init` created is [yours](#your-game-is-yours).

Optional extras: `bcrypt` for stronger password hashing (a salted SHA-256
fallback is built in), `websockets` for browser clients.

## What a verb looks like

`verbs/17/jump.py` — the `jump` command available in every IC room:

```python
"""
Jump across a gap or obstacle.

Usage: jump <exit>
"""

if not args:
    pobj.msg("Jump what?")
    return

# Can the character act? do_wait covers roundtime as well as the
# immobilising conditions, and emits its own message.
if pobj.do_wait():
    return

pos = pobj.position or 0
if pos:
    pobj.msg("You can't do that in your current position.")
    return

# Match exit in room contents
exit = pmatch(dobj, pobj, list(pobj.location.contents))
if not exit or not exit.is_exit:
    pobj.msg("Jump what?")
    return

if exit.jumpable:
    call_verb(exit, 'invoke')
elif exit.climbable:
    pobj.msg("You have to climb that!")
else:
    pobj.msg("You can't jump that!")
```

No imports, no boilerplate: the verb namespace arrives pre-loaded with the acting player (`pobj`), parsed arguments (`args`, `dobj`, `iobj`), object matching (`pmatch`), cross-object calls (`call_verb`), and the rest of the builtin library. Objects are matched the way a player thinks — `jump gap`, `jump 2nd rope` — and the verb reads top to bottom like the action it performs.

## Your game is yours

```
mygame/
    world.db        the live world -- objects, properties, players
    verbs/          the world's code, one file per verb
    game/           your own Python, imported by verbs
    megamoo.toml    what to serve, and where
```

`verbs/` and `game/` are the source, and belong in your version control.
`world.db` is the running state — it holds player data and password
hashes, and `megamoo init` gitignores it for you.

Game-specific Python goes in `game/` and a verb imports it the ordinary
way:

```python
from game.combat import swing
```

which is the same spelling verbs already use for `moo.objects`. That is
the whole extension mechanism — no plugin registry, no hooks, nothing
new to learn.

The starter world comes with 312 verbs, 228 of them typeable: player
commands, staff and building tools (73 `@`-commands), rooms and exits,
containers and furniture, and character generation. They are copied into your game, so
they are yours to edit — the engine keeps no copy you have to merge
against.

## What makes it different

**You change the world while people are standing in it.** Edit a verb in
your editor and the running server picks it up; edit one from inside the
game with `@program` and the file is written for you. No build, no
restart, no deploy step, no players disconnected. The file on disk is the
source of truth and the running world follows it — in both directions.

**The in-world language is Python itself.** Not a MOO-like language, not a
scripting subset: verb bodies are Python source with the whole standard
library available. `#42` resolves to object 42 and `$utils` to a system
object; that is the entire preprocessor.

**Your game is a directory the engine never touches.** `megamoo init`
gives you `verbs/`, `game/` and a world file that are yours. Upgrading is
`pip install --upgrade megamoo` — there is no fork to merge, because you
never had a copy of the engine to begin with.

**Nothing to install but Python.** Zero third-party dependencies. The
engine runs on the standard library, so a world deploys anywhere Python
runs, with no build toolchain and nothing to compile.

Underneath: an `asyncio` core serving Telnet and WebSocket at once with
classic MUD protocol negotiation (MXP, GMCP, MSDP, MSSP); SQLite
persistence in WAL mode with a lazy object cache and periodic
checkpointing; LambdaMOO-style single-parent inheritance with a flattened
ancestor cache; a parser that handles articles, ordinals (`get 2nd
sword`), adjective–noun matching and prepositions; tick-driven timed
effects that survive restarts; managed tasks with time limits,
`suspend(5)`, and fork-bomb protection; and a gender-aware emit
substitution engine so actor, target and room each read correct prose.

**Accessibility is part of the engine's job**, not a plugin — per-player
screenreader mode, ANSI-aware wrapping that measures visible width, and
the option to turn server-side wrapping off entirely. See
[Accessibility](#accessibility).

## Documentation

**[Read the guide →](https://malifaxlax.github.io/megamoo/)**

| | |
|---|---|
| [What MegaMOO Is](https://malifaxlax.github.io/megamoo/) | Start here |
| [Getting Started](https://malifaxlax.github.io/megamoo/getting-started.html) | Your first room, object and verb |
| [Building Worlds](https://malifaxlax.github.io/megamoo/rooms.html) | Rooms, exits, objects, shops |
| [Writing Verbs](https://malifaxlax.github.io/megamoo/verbs.html) | The programming model |
| [Command Reference](https://malifaxlax.github.io/megamoo/commands.html) | All 75 staff commands |
| **[Coming from LambdaMOO](https://malifaxlax.github.io/megamoo/moo-compat.html)** | **Importing an old database, and porting its verbs** |
| [The Web Client](https://malifaxlax.github.io/megamoo/web-client.html) | Playing in a browser |

The engine's internals — object model, parser, verb types, the systems
underneath — are in the developer manual under [`docs/manual/`](docs/manual/).

## Inside the engine

| Subsystem | Module | What it does |
|---|---|---|
| Server core | `moo/server.py` | Event loop, serialised verb execution (one verb at a time, via the baton in `moo/verb_baton.py`), context propagation, graceful shutdown/restart |
| Networking | `moo/network.py` | Telnet/WebSocket connections, protocol negotiation, color and wrapping |
| Database | `moo/database.py` | SQLite persistence, object cache, checkpointing |
| Object model | `moo/objects.py` | Inheritance, properties as native Python attributes, flags, tags |
| Parser | `moo/parser.py` | Command → verb/direct-object/preposition/indirect-object resolution |
| Verbs | `moo/verbs.py` | Verb compilation, preprocessing, caching, dispatch |
| Matching | `moo/match_utils.py` | `pmatch`/`bmatch` natural-language object matching |
| Tasks | `moo/tasks.py` | Time-limited execution, suspend/fork, scheduling |
| Effects | `moo/effects.py` | Tick-driven buffs/debuffs with persistence |
| Permissions | `moo/permissions.py` | Wizard/programmer/owner hierarchy, quotas |
| Builtins | `moo/builtins.py` | The function library injected into every verb's namespace |

## Porting from LambdaMOO

There is no MOO-language interpreter here, so existing MOO verbs have to be
rewritten in Python. The good news is that the hard part of a MOO — the object
model — carries over directly, because MegaMOO uses the same one: single-parent
inheritance, properties and verbs living on objects, ownership and permission
bits, `$name` system references.

What changes is the verb body. The usual substitutions:

| LambdaMOO | MegaMOO |
|---|---|
| `player:tell("...")` | `pobj.msg("...")` |
| `this.location` | `this.location` (unchanged) |
| `$string_utils:...` | `su....` — the LambdaMOO string utilities are provided, alongside Python's own `str` methods |
| `$object_utils:...` | `ou....` |
| `pass(@args)` | `pass_(*args)` |
| `suspend(n)` | `suspend(n)` — same meaning: other verbs run, yours resumes on the next line |
| `E_PERM` and friends | `E_PERM` — first-class values here too, so they can be returned, stored and compared as well as raised |
| `player:my_huh(...)` | verb dispatch through the parser |
| `length(x)`, `tostr(a, b)` | `len(x)`, `f"{a}{b}"` |
| `{1, 2, 3}`, `x[1]` | `[1, 2, 3]`, `x[0]` — lists are 0-based |

A world's *content* is the part worth preserving — the rooms, the objects, the
descriptions, the shape of the hierarchy. Verb code is usually the smaller and
more replaceable half, and a lot of what old MOO utility packages exist to do
(string formatting, sorting, list manipulation) is already in Python's standard
library.

`@import` reads a LambdaMOO database — format versions 1 through 4, so
LambdaMOO up to 1.8 — and carries the objects, hierarchy and properties across,
remapping object references as it goes. Verb code comes too, but inert: it is
kept verbatim under a docstring recording where it came from and how to port
it, stored hidden and without the execute permission, so your old code sits on
the right objects under the right names instead of in a tarball. `@grep
'UNPORTED MOO SOURCE'` lists what is left. See
[Coming from LambdaMOO](https://malifaxlax.github.io/megamoo/moo-compat.html) for the whole process.

## Who may write verbs

Verb code is ordinary Python, executed with ordinary Python privileges. A
verb can `import` any module, open files, and reach `__builtins__`. That is
deliberate — it is what "the in-world language is Python itself" means, and
it is why the standard library is genuinely available rather than a curated
subset.

The consequence is that **the security boundary is who can create a verb,
not what a verb can do once created.** `@program`, `@adverb` and `eval` are
gated at **gm3**. Anyone holding gm3 can run arbitrary code as the server
process and should be considered as trusted as the person running it.

That is the same trade classic MOO made in reverse. There, ordinary players
could program safely because the MOO language *was* the sandbox — a small VM
with no imports and no host access. Here the in-world language is Python
itself, which is the point, and Python has never been safely sandboxable
in-process. So the boundary moves to who may write a verb, and a coder is
staff.

**What gm3 cannot do is reach anybody else's things.** Ownership decides
that, not level. A verb runs as its owner, so a builder's code writes their
own objects and is refused on yours; `auth` is owned by `#0` with `rc` perms,
so no amount of `@set`, `@adprop` or `@rmprop` will grant a level. Authority
is not inherited either — `auth_level()` reads an object's own property, so
descending from a wizard grants nothing. Those are enforced by the engine,
not by convention. None of them is a defence against a coder who means harm,
and nothing running in this process could be.

Two things follow:

- The permission-checking `getattr`/`setattr` in the verb namespace are a
  guard rail for well-behaved code, not an enforcement boundary. Verb code
  that wants the unchecked versions can reach them.
- **Think carefully before granting gm3 broadly.** Classic MOO let ordinary
  players program, which worked because the MOO language was itself the
  sandbox. MegaMOO has no equivalent boundary, so opening programming to
  untrusted players would hand them the host account.

If you want a world where players write code, that needs a real sandbox —
a separate piece of work, and not something the current permission levels
provide.

## Upgrading a world you already built

`megamoo init` copies the starter out and the world is yours from that
moment — the engine keeps no copy to merge against. The other side of that
bargain used to be that fixes to the starter never reached a world that
already existed.

```bash
megamoo upgrade world.db          # reports; writes nothing
megamoo upgrade world.db --apply  # brings the safe changes across
```

It compares your world against the version it was created from and against
the current starter, and sorts every verb, object and property: untouched
here and changed upstream is safe to take; changed by you is yours and is
left alone; changed by both is a conflict, reported and untouched. It backs
the world up first and refuses while a server has it open.

Every object carries an opaque identity from creation, so pairing survives
renumbering and renaming. Worlds created before 0.10.0-beta23 pair by
object number instead — which works until something renumbers, and is
refused rather than guessed at when it does.

## Accessibility

MegaMOO is developed by a quadriplegic (C1–C2) programmer using a head-pointer input device at about 30 words per minute, in collaboration with AI pair-programming tools. That vantage point shapes the engine:

- **Screenreader mode** (`screenreader` command) strips all ANSI color and visual decoration from output, per player, persistently. It is reachable from anywhere, character creation included, so it can be turned on before the first screen rather than after it.
- **Output that reads aloud.** The building and introspection commands — `@ps`, `+props`, `+verbs`, `@list`, `+pron`, `@dig/types` — answer screenreader mode with one labelled fact per line instead of a padded table, and character creation drops its box borders. Sighted output is unchanged.
- **Verb files that lint clean.** Verb code is Python with its context injected, which a linter reports as hundreds of undefined names. Your game ships a `ruff.toml` and a type stub that declare them, so an editor is usable from the first minute — which matters most if you navigate code by tooling rather than by eye.
- **ANSI-aware wrapping** computes visible text width so escape sequences never break line layout; server-side wrapping can also be disabled entirely (`WRAP_WIDTH = 0`) for screen readers and clients that reflow.
- Text-native gameplay: everything in the world — movement, building, programming — is fully playable through assistive input at any typing speed, because a MOO rewards thought, not reflexes.

Text worlds were the original accessible online games. MegaMOO treats keeping them that way as part of the engine's job.

## MCP Server (AI Integration)

Claude Code (or any MCP client) can drive the running game directly: execute commands as a TestBot character, inspect and edit live objects and verbs, and read server logs — all without touching the database by hand.

### Architecture

```
Claude Code ──stdio──> tools/megamoo_mcp.py ──TCP/JSON──> ApiServer (port 7778)
                         (MCP bridge)                       inside running MegaMOO
                              │
                              └──reads──> megamoo.log (works even when server is down)
```

`tools/megamoo_mcp.py` is a standalone FastMCP bridge. The game server gains no new dependencies.

### One-time setup

```bash
pip install mcp
megamoo --dev                                              # API on, token reused
claude mcp add megamoo -e MEGAMOO_API_TOKEN=<token> -- python3 tools/megamoo_mcp.py
```

### Tools (17 total)

**Game tools** — require the server to be running:

| Tool | Description |
|---|---|
| `run_command` | Execute a game command as TestBot; returns all output (color stripped) |
| `disconnect_testbot` | Cleanly unpuppet TestBot via the normal `on_unpuppet` path |
| `get_object` | Full object info: name, parent, flags, properties, verbs |
| `get_location` | Object's current location (objnum + name) |
| `list_contents` | Contents of a room or container (objnum + name pairs) |
| `list_verbs` | Verb names defined on an object, optionally including inherited |
| `get_verb` | Source code of a verb |
| `set_verb` | Write or replace a verb's source code |
| `delete_verb` | Remove a verb from an object |
| `list_properties` | Property names defined on an object, optionally including inherited |
| `get_property` | Value of a single property |
| `set_property` | Write a property value (any JSON-representable type) |
| `eval_code` | Evaluate arbitrary Python in the game's verb context |
| `search_verbs` | Full-text search across all verb source files |
| `search_objects` | Search objects by name or description |

**Disk tools** — work even when the server is down:

| Tool | Description |
|---|---|
| `tail_log` | Last N lines of `megamoo.log`, with optional regex filter |
| `server_status` | API reachability; if up, includes uptime and player count |

### Notes

- TestBot is auto-created on first `run_command` if no character named TestBot exists under `#5 ICharacter`. To use a specific character instead, set `testbot_objnum` in the API config section before starting the server.
- The integration test suite (`python3 -m pytest tests/`) boots its own server on ports 7901/7902 against a scratch copy of the starter world, so it can run while a dev server is up. Two caveats: the test subprocess appends to the shared repo-root `megamoo.log`, and the snapshot is a plain file copy — if the live server is writing heavily at that moment, the copy could be torn. When in doubt, stop the server or run only the unit tests: `python3 -m pytest tests/ --ignore=tests/test_integration_api.py`.
- Design spec: [docs/superpowers/specs/2026-06-12-mcp-server-design.md](docs/superpowers/specs/2026-06-12-mcp-server-design.md)

## Status

Active development. The engine runs a private in-progress game world (character generation, building tools, and the accessibility layer are all exercised daily); it has not yet had a public multiplayer deployment. Near-term roadmap:

- Web client polish on the WebSocket path
- Documentation for the builtin library and verb-authoring conventions

## Credits

- **LambdaMOO** by Pavel Curtis et al. — the object model, permission system, and the idea that a world should be programmable from the inside.
- **Evennia** — inspiration for network protocol handling and the tag system.

## License

MIT — see [LICENSE](LICENSE).
