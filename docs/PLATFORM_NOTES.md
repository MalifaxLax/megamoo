# Platform Notes

*An outside read on what MegaMOO would need to become a place people build text
games, and what it could offer that nothing else does. Written 2026-08-08 against
the trees at `~/megamoo`, `~/sfdev` and `~/mooport`, plus current web research on
the competition. Written to be useful, not encouraging.*

---

## 1. What MegaMOO is today, grounded in the code

### Measured, not claimed

| Thing | Measured |
|---|---|
| Engine (`moo/*.py` + `moo/web/*.py`) | **32,042 lines** |
| Launcher + tools (`megamoo.py`, `tools/`) | 1,820 lines |
| Shipped world content (`moo verbs/`, 199 files) | 13,726 lines |
| Engine tests (`tests/`, 17 files) | 3,667 lines, ~277 test functions |
| Web client, **first-party only** (js/css/html) | **2,467 lines** |
| Web client, vendored `wasmoon` (Lua→wasm) | 2,941 lines |
| Developer manual (`docs/manual/*.md`) | 3,556 lines |
| `~/mooport` | 8,960 lines |
| Third-party runtime dependencies | **0** (stdlib only; `bcrypt`/`websockets` optional) |

**Two numbers in circulation are wrong and should be corrected before anyone
audits them.** The README says "roughly 75,000 lines of Python"; the public repo
totals about **53,000 lines including tests, verbs and docs**, and about 34,000 if
you mean "Python the project wrote." Likewise the web client is often described as
~12,900 lines; the first-party client is **~2,500**, and the rest is a vendored Lua
runtime plus a binary `.wasm` blob counted as text. These are not fatal, but a
project with 4 stars trying to recruit builders cannot afford a number that a
skeptic can disprove with `wc -l` in ten seconds. Fix them. The real numbers are
respectable on their own.

### What actually exists (verified)

- **A real MOO object model.** Single-parent inheritance with a flattened ancestor
  cache, properties as native Python attributes, ownership/permission bits,
  `$name` system references, `#N` object references resolved at the input layer.
  `moo/objects.py` is 2,021 lines and it is the genuine article, not a veneer.
- **Python verbs stored in the database, mirrored to disk, hot in both
  directions.** `@program` compiles, installs live, and writes
  `moo verbs/<objnum>/<verb>.py`. A background watcher (`dev.autoreload_verbs`,
  2s poll) pulls disk edits back into the running server. No restart, no reload
  command, players stay connected. This is the single most distinctive mechanical
  fact about the project.
- **A builder toolkit of ~66 `@`-commands on `#3`**, including five distinct exit
  kinds (`@open`/`@vopen`/`@gopen`/`@dopen`/`@copen`/`@jopen`) with automatic
  return exits, `@dig`, `@make`, `@desc`, `@adjective`, `@adprop`/`@set`,
  the success/osuccess/failure/ofailure/drop/odrop message pairs, and a genuinely
  good inspection set (`@examine`, `+show`, `+props/all`, `+verbs/all`, `@grep`,
  `+decompile`).
- **A real parser.** Articles, ordinals, adjective–noun, possessives, prepositions,
  switch syntax (`look/brief`), separate player (`pmatch`) and staff (`bmatch`)
  matching modes.
- **Telnet + WebSocket on one asyncio loop**, with MXP/GMCP/MSDP/MSSP and
  ANSI-aware wrapping that measures visible width.
- **A first-party browser client served by the game server itself**, no build step,
  one port. Terminal + scrollback, an automap, a script manager with two sandboxed
  hosts (JS in a Web Worker with a blocklist; Lua in a wasm VM with no JS bridge),
  and — the interesting part — **script-declared UI panels described as data**
  (`text`/`bar`/`gauge`/`row`/`stack`/`table`) so no script in either language can
  inject markup.
- **The automap is better engineering than it needs to be.** `moo/roommap.py`
  derives a canonical grid from the exit graph once, server-side, then runs a
  relaxation pass with cell-swapping to fix rooms claimed by the wrong neighbour —
  81% → 96% exit alignment on the shipped world. Every client draws the world the
  same way. Exit destinations are deliberately withheld so the map is a frontier,
  not a spoiler.
- **An MCP bridge** (`tools/megamoo_mcp.py`, standalone, adds no engine deps):
  17 tools, including `run_command` as a headless TestBot character on a
  `VirtualConnection`, plus `get_verb`/`set_verb`/`eval_code`/`search_verbs` and
  multi-server discovery (`list_servers`/`use_database`).
- **Effects, tasks, tickers, quotas.** `suspend(n)` genuinely parks a verb thread
  and resumes mid-verb with the stack intact (`moo/verb_baton.py`), which is the
  right answer and better documented than most engines' equivalent.
- **`~/mooport`** reads LambdaMOO textdumps v1–v4, carries objects/hierarchy/
  properties across, and stores unported verb source inert, hidden, non-executable,
  under a docstring saying where it came from. `@port` does an assisted MOO→Python
  translation and marks what it will not guess. This is honest tooling and it is
  well scoped.
- **Screenreader mode and `WRAP_WIDTH = 0`** are real, per-player, persistent.

### What the code also tells you, less flatteringly

- **There is no separation between "the engine" and "your game."** You clone the
  repo and edit `moo verbs/` *inside the engine checkout*. There is no
  `pip install`, no `pyproject.toml`, no `megamoo init mygame`, no game-directory
  concept. The consequence is that every serious user forks the engine — and the
  proof is in the owner's own tree: `~/sfdev/moo/` has diverged from `~/megamoo/moo/`
  and now contains `combat_data.py`, `chargen_data.py`, `moo_files.py` and `grid/`.
  `moo verbs/800/critter_loop.py` opens with `from moo.combat_data import
  get_weapon_stat`. **The flagship game cannot be built on the shipped engine.**
  That is the most important structural fact in this document.
- **World content is not version-controlled.** Verb *code* is on disk and diffable —
  genuinely good, and half of a real differentiator. But rooms, objects, exits,
  descriptions, properties and the hierarchy live only in SQLite. `git diff` shows
  you behaviour and not the world. `@dump`/`@load` is per-object, explicitly drops
  location/contents/children, and does not remap object references (it counts them
  and asks you to fix them by hand). There is no area, zone, or region unit.
- **There is no sandbox, by design and by admission.** Verb code is ordinary Python
  with `__builtins__` unpinned; `import`, `open`, and the host account are all
  reachable. `@program`/`@adverb`/`eval` are gated at gm3, and the README says
  plainly that gm3 ≈ shell. The README's honesty here is a credit to the project.
  The strategic cost is severe and is discussed in §3.
- **One verb runs at a time**, globally, by design (`verb_baton.py`). This is the
  right call for correctness and it will be a real ceiling if a world ever gets busy.
- **No CI, no Dockerfile, no `CONTRIBUTING.md`, no issue templates, no releases,
  no PyPI presence, no public playable instance.** The public repo was created
  **2026-08-01** and has **4 stars**.
- **Engine tests are decent; content tests do not exist.** There is no way to write
  a test for a verb.

---

## 2. Honest competitive read

### Evennia — the one that matters

- **2,084 stars, 766 forks, 130 watchers, 10,509 commits, created 2014, pushed
  2026-08-05. v6.1.0 on PyPI, 2026-07-05, Python 3.12+.** Active, institutional,
  twelve years old.
- Dependency weight is real: 14+ direct dependencies including **Django 6.0.x and
  Twisted 24.11+**, plus DRF, autobahn, pyyaml, inflect, lunr, simpleeval. A real
  install pulls 40–60 packages. MegaMOO pulls zero.
- **What Evennia does better, specifically:**
  - **`pip install evennia && evennia --init mygame && evennia migrate && evennia
    start`.** Four commands, and you have a running game, a website, a Django
    admin, and a webclient — *and your game lives in your own git repo, separate
    from the library.* This is the whole ballgame and MegaMOO does not have it.
  - **53 contribs.** Not a checklist item — a working answer to "how do I do X on
    day one." `turnbattle`, `crafting`, `clothing`, `containers`, `puzzles`,
    `talking_npc`, `traits`, `buffs`, `dice`, `barter`, `mail`, `achievements`,
    `cooldowns`, `rpsystem` (poses, masks, languages, recognition), `gendersub`,
    `character_creator`, `building_menu`, `multidescer`, `evscaperoom`, and an
    **`llm`** contrib that already wires NPC chat to an LLM server.
  - **Prototypes and `@spawn`, with an OLC menu.** Reusable object templates with
    an in-game wizard. MegaMOO's shipped `mm.db` has no equivalent; `~/sfdev` has
    spawners as bespoke game content.
  - **`xyzgrid`** — coordinate grid, pathfinding, limited-view maps — and
    `mapbuilder` (build rooms from an ASCII drawing). MegaMOO's automap is
    arguably nicer *for the player*; Evennia's grid is a *building* tool.
  - **Batch processors** (`batchcmd`/`batchcode`) — a text file that builds a
    world. One-way, but it is a world-as-text story and MegaMOO has none.
  - **Documentation volume and a maintained Discord.** MegaMOO's manual is
    genuinely well-written — better prose than Evennia's, in places — but it is
    3,556 lines against a documentation site with tutorials, a full beginner
    track, and twelve years of forum answers.
- **What MegaMOO does better than Evennia:** live verb editing from inside the
  running world with two-way hot reload; a lighter and more auditable footprint;
  a web client with no Django in front of it; a richer exit vocabulary; the MCP
  bridge. That is a short list, and "Python verbs" is **not** on it — Evennia is
  also pure Python. The difference is *where the code lives and when it takes
  effect*, not the language. Do not market it as the language.

### The MOO family — and mooR specifically

**mooR is the more dangerous competitor for the position MegaMOO wants**, and it
is further along than the framing "a Rust rewrite" suggests. 215 stars, created
2022, pushed 2026-08-06, on a 1.0 release-candidate track. What it has *today*:

- **It runs existing LambdaMOO databases with real workloads.** MegaMOO explicitly
  cannot — `@import` carries objects and properties but leaves verbs inert. For
  anyone with a 30-year-old world, that is not a close call.
- **Directory-based import/export for version control**, plus `load_object` /
  `dump_object` builtins with **conflict detection** — i.e. mooR is actively
  shipping the "git for worlds" story right now.
- **An official web client (Meadow) with a published `web-sdk` package**, a
  property editor and themes; a **live public testbed** (Timbran Hotel) you can
  connect to today.
- **An OpenAPI 3.1-specified HTTP API** with versioned routes, and a FlatBuffers
  RPC protocol explicitly intended to let tools be written in Python, JS, C++ or Go.
- A fully multithreaded transactional engine — no global "one verb at a time."
- An extended MOO language (maps, lambdas, list comprehensions, lexical scoping,
  64-bit ints, UTF-8).
- **AGPL-3.0**, against MegaMOO's MIT. That is a genuine MegaMOO advantage for
  anyone who wants to run a closed world.

MegaMOO's entire argument against mooR is *"Python instead of the MOO language."*
That is a real argument — vastly larger talent pool, the whole stdlib, no DSL to
learn, AI coding assistants that already know the language. But it is **one**
argument, and it costs the sandbox that mooR keeps for free, because in mooR the
language *is* the boundary. Be clear-eyed: MegaMOO trades MOO's defining social
affordance (anyone in the world can program the world) for Python. That trade may
be correct. It is not free, and the marketing currently does not acknowledge it.

**ToastStunt** (92 stars, pushed 2026-06-05) is the practical LambdaMOO fork
running real MUDs (Miriani, ChatMud). Small but alive. **Cold/ColdC** is
historically interesting and effectively dormant.

### Diku/Merc/ROM/CircleMUD and CoffeeMUD

What a builder gets on day one that MegaMOO does not: **area files**. A ROM `.are`
file is a shareable, diffable, human-editable unit of world, and a thirty-year
corpus of them exists. **OLC** (in-game creation) with mob/object/room editors that
are menu-driven, not command-driven. Mob programs / DG scripts for behaviour.
Combat, classes, levels, spells, shops, quests — all present, all working, all day
one, all with decades of tuning. It is 1990s architecture in C with a
levels-and-loot worldview baked in, which is exactly why people leave it, but
nobody leaves it because *building* is hard.

**CoffeeMUD** (230 stars, pushed 2026-08-03, still maintained by one person after
25 years) ships in one JAR with OLC, XML area import/export, a web server, a mail
server, MSP/MXP/GMCP, and an enormous built-in content library. It is the
existence proof that a solo maintainer can carry a full platform for decades — and
also that doing so wins you ~230 stars.

### Node/JS

**Ranvier: 854 stars, last push 2023-07-11.** Effectively dormant, whatever the
website implies. Its bundle system is a good idea worth stealing (world content
as installable, versioned packages) and its abandonment is a useful warning about
what a nice architecture is worth without a maintainer.

### Interactive fiction — where the authoring bar actually is

This is the comparison MegaMOO should take most seriously, because these tools
are not competitors for players and are the standard for *authoring*.

- **Twine** — you get a working, browser-playable, shareable game in about ninety
  seconds, with a visual node graph, no install, no server, no account.
- **Ink** — plain text, version-controlled by nature, embeds in a real production
  pipeline, live preview in Inky.
- **Inform 7** — natural-language source, an integrated IDE with a world index,
  transcript-based regression testing (`test me`), and the best debugging story in
  text gaming.
- **IFComp draws 100+ entries a year.** That is more finished text games per year
  than the entire MUD scene ships.

What all three have that MegaMOO does not: **you can see your thing running within
a minute of deciding to try, and you can hand someone a link.** MegaMOO's current
answer is "clone a repo, run a Python script, telnet to localhost." That gap is
not about features. It is about the first five minutes.

### AI-native text gaming

Occupied, and mostly commodity. AI Dungeon still exists with multiplayer and
worldbuilding tools. "MUD AI" markets an AI-run text dungeon with a real-time AI
GM and NPCs with memory. Evennia ships an `llm` contrib; `eleniums/mud-ai` is an
Evennia + local-LLM MUD on GitHub. The recurring lesson from the credible ones is
the one MegaMOO should internalise: **separate narration from resolution** — the
rules engine decides, the model describes. Any MegaMOO LLM feature that ignores
that is building the bad version of something already commoditised.

### The market, honestly

MUDStats tracks ~734 active MUDs. New engines are not the bottleneck; **finished
worlds are.** Anyone building an engine to grow the genre is fixing the part that
was never broken. The reason to build MegaMOO is that *authoring* a multiplayer
world is still miserable — not that there is a shortage of servers.

---

## 3. Gaps — table stakes to not lose builders

Ordered by how quickly their absence ends an evaluation.

### T1. There is no "your game." (Fatal, and already proven fatal internally.)

Every other item on this list is downstream. Without a library/game split you
cannot ship an upgrade, cannot have a starter template, cannot have contribs,
cannot host anything, cannot let two people build different games on one engine
version. The evidence is `~/sfdev/moo/combat_data.py` — the owner's own second
game required forking the engine. A third user will fork it too, and then there is
no project, only a family of orphans.

**What's needed:** `pyproject.toml`; `pip install megamoo`; `megamoo init mygame`
producing a game directory (`game.db`, `verbs/`, `config.json`, `.gitignore`) that
is the user's git repo; a documented extension point so game-specific Python
(`combat_data.py`) lives in the game directory, not `moo/`.

### T2. No world-content export/import, therefore no shareable areas

`@dump`/`@load` is single-object, drops relationships, and doesn't remap refs.
Diku has area files. CoffeeMUD has XML. Evennia has batch processors and xyzgrid.
mooR is shipping directory-based export with conflict detection **now**. MegaMOO
has nothing at the granularity anyone actually shares. Until an area can round-trip
through a text format, nobody can give anyone a tavern.

### T3. No prototype/spawner system in the shipped database

Evennia has prototypes + `@spawn` + an OLC menu. `~/sfdev` has spawners as
one-off game code. A builder making the tenth guard should not be making the
tenth guard by hand.

### T4. No content testing

277 engine tests and no way to assert that `get sword` works. Inform 7 has had
transcript regression testing since 2006. With hot reload and a headless
`VirtualConnection` already in the tree, this is unusually cheap here — see §6.

### T5. No sandbox, and therefore no untrusted builders

Stated honestly in the README, which is right. Understand what it forecloses:
shared hosting of other people's worlds, letting players program (MOO's original
premise), classroom use, and any "invite a friend to build with you" story where
the friend isn't trusted with your shell.

**Do not try to sandbox CPython.** It has been attempted repeatedly and the
attempts lose. The two honest paths are (a) accept "trusted builders only" and
solve openness with *forking* instead of *sharing* (see §4), or (b) OS-level
isolation — one container per world. (b) is real work but it is engineering, not
research.

### T6. Distribution and credibility hygiene

No CI, no Docker one-liner, no releases, no `CONTRIBUTING.md`, no public instance,
no PyPI. Plus the two inflated numbers in §1. Each is individually small; together
they read as "one person's private project," which is exactly the impression that
loses a builder who is comparing three options in an afternoon.

### T7. Onboarding

The manual is a *reference*, and a good one. There is no tutorial that takes an
unfamiliar person from nothing to "I built a room and a thing that does something
and my friend walked into it." Evennia's beginner tutorial is its most valuable
asset and it is not close.

### Not table stakes — deliberately

- **A quest/dialogue DSL.** Every engine has one; none is loved. Python verbs
  already express quests better than a DSL will. Ship one *example* quest as
  content, not a subsystem.
- **Combat scaffolding.** `~/sfdev` has a full Rolemaster port and it is game
  content. Combat is genre; the engine should stay out of it. Ship it as a
  publishable module once T1 exists.
- **Chasing 53 contribs.** You lose that race and it is not why anyone would switch.

---

## 4. Differentiators — the case for choosing this over Evennia

Only three of these survive scrutiny. The rest are things the owner values more
than the market does, and it is worth being blunt about which is which.

### D1. The world is editable while it is running, from inside and outside, with no restart

This is the real one. Verbs live in the database *and* on disk, synced both ways,
hot. An `@program` session, a text editor, a `git checkout`, and an AI agent with
plain file tools are all valid ways to change the world, **while players are
standing in it**. Evennia's model is edit-module-and-reload. mooR's is edit-in-world
or dump/load. Inform's is compile. Nothing else in text gaming has the full
two-way loop with zero downtime.

The sentence that makes this a *product* rather than a *fact*:
**a MegaMOO world has no build step and no deploy step.**

### D2. The MCP bridge — and the fact that the architecture makes agentic authoring actually work

An LLM agent can, right now: hold a character in the world, type commands and read
what the world says back, inspect any object's properties and parents, search all
verb source, write a verb, and see the effect on the next invocation — no restart,
no rebuild, players still connected. That is an unusually good fit between a tool
and an architecture, and it is not a coincidence: it works because a MOO is a live
introspectable object database rather than a compile-and-deploy pipeline.

Be skeptical about the moat. An Evennia MCP server is a weekend project for
someone motivated, and mooR's OpenAPI already exposes most of the same surface.
What is hard to copy is not the bridge; it is the **no-restart, in-world,
inspect-try-fix loop** the bridge plugs into. Evennia can bolt on MCP but an agent
editing Evennia is still editing files and reloading a server. So D2 is really D1
with a handle on it — which is fine, and is the correct way to pitch both.

**Honest caveat in the current code:** there is one shared TestBot behind a
`testbot_lock`. Single-agent today. Any serious version of this needs N virtual
connections.

### D3. The world ships its own UI to the browser

`moo.panel(id, spec)` with a fixed widget vocabulary and no markup path is a
better idea than it currently gets credit for. It means a *world author* — not a
client author — decides what the player's HUD looks like, in Lua or JS, with no
install, no plugin, and no ability to inject HTML. Mudlet does this better for
one client with decades of ecosystem; nobody does it *from the server, to every
player, with no client install.* Combined with GMCP republication on the client's
event bus (a new server package is scriptable with zero client changes), that is
a coherent and unusual design.

### Things being sold as differentiators that are not

- **"Python verbs."** Evennia is pure Python too. The differentiator is D1.
- **"Zero dependencies."** Builders do not choose engines by dependency count, and
  `pip install` is a solved problem. Zero-deps is real and worth keeping — for
  auditability, longevity, weird hosts, and because it makes a single-file or
  single-container distribution trivial — but it wins zero arguments on its own.
  Note the irony that the *absence* of a `pyproject.toml` is currently a bigger
  liability than the presence of dependencies would be.
- **"Multiple databases running concurrently."** You can run N Evennia processes
  too. The only genuinely nice part is that the MCP bridge is multi-server aware.
  That is a developer convenience, not a reason to switch.
- **"Multiplayer by default."** True and important, but it is not a feature — it
  is what a MOO *is*. Its value is as *positioning*, and there the observation is
  sharp and currently unstated: **the IF tools have the best authoring and no
  multiplayer; the MUD engines have multiplayer and 1990s authoring. Nobody
  occupies "multiplayer with IF-grade authoring ergonomics."** That is the
  sentence this project does not yet have on its front page.

---

## 5. The innovation swing, ranked by honest odds

Ranked by (impact × probability a very small team finishes it).

### 1. Agent-as-inhabitant — LLM characters that play through the real parser
**Confidence it is genuinely novel: high. Confidence it becomes a reason people
adopt MegaMOO within a year: medium (~40%).**

Everyone's LLM NPC is a chatbot bolted to a description string; it hallucinates
actions the world cannot perform and its memory is a transcript. MegaMOO already
has the pieces for the better version: `VirtualConnection` + TestBot means an
agent connects **as a character**, and issues `look`, `go north`, `get lantern`,
`say ...` through the identical parser and identical permission path as a human.
Consequences follow that are not available to a bolted-on chatbot:

- It physically cannot take an action the world does not support. The parser is
  the guardrail; no prompt engineering required.
- Its memory *is* world state — it can be given properties, an inventory, a
  location, and other characters can inspect it.
- Narration and resolution are already separated, because the game resolves and
  the model only chooses commands. This is exactly the design the credible
  AI-GM projects converged on, and MegaMOO gets it structurally rather than by
  discipline.
- Because verbs are hot, an agent NPC's behaviour is editable while it lives.

Why only ~40%: making an agent *fun* rather than uncanny is a design problem, not
an engineering one, and nobody has solved it. Token cost per NPC per tick is real.
And the single-TestBot lock has to go first. But this is the one idea on the list
that both falls out of the existing architecture and is not already being done
better elsewhere.

**Note it is a differentiator for the engine even if the NPCs are mediocre**,
because the same machinery is how you test the world (§6).

### 2. Fork-a-world, not share-a-world
**Confidence: medium-high (~55% it ships; high that it is the right idea).**

The sandbox problem has an escape hatch that avoids sandboxing entirely. If a
world is a **git repository** — verbs (already are) plus world content as text
(T2) plus the database as a derived artifact — then openness stops requiring
trust. You do not let a stranger program *your* world. They fork it, build in
theirs, and send a pull request you read like any other diff. The GitHub model,
applied to a MOO.

This makes several other things fall out for free: world content becomes
reviewable, areas become shareable, a "starter worlds" gallery becomes possible,
and education (§8) stops needing a sandbox because every student gets their own
world.

The risk is that **mooR is building this right now** (`dump_object`/`load_object`
with conflict detection, directory-based export). The lane is open but it is
closing, and mooR will get there first unless this is prioritised. Getting there
second is still fine if MegaMOO's version is better — a MOO's content genuinely
does round-trip to text more cleanly than most game data — but "second and worse"
is not fine.

### 3. Instant-try in the browser
**Confidence it works if built: high. Confidence it gets built well: medium (~45%).**

One URL. No account, no install, no telnet. You are standing in a room, you type
`@dig ic = My Room`, you walk into the thing you just made. That is Twine's
ninety seconds applied to a multiplayer world, and the web client already does
90% of it. This is how curiosity converts.

The trap: hosting other people's worlds means executing their arbitrary Python as
you. So this is either (a) a **read-mostly demo world** with building enabled and
a periodic reset — cheap, safe, and 80% of the value — or (b) real per-tenant
containers, which is genuine ops work with real abuse surface and a monthly bill.
**Do (a). Do not do (b) this year.**

### 4. World content as text (the enabling half of #2)
**Confidence: high (~70%) — this is engineering, not invention.**

Rooms, objects, exits, descriptions, properties exported as readable files with
**symbolic references rather than object numbers** (`$tavern/bar` not `#5041`),
importable into a fresh database. This is a chunk of careful work — the objref
handling in `_store_objref` and `preprocess_objrefs` already shows the shape of
the problem — but nothing about it is speculative. It unlocks #2, T2, testing,
diffable review, and the entire "git for worlds" pitch. Rank it high not because
it is exciting but because everything exciting depends on it.

### 5. Accessibility as a genuine differentiator
**Confidence it is real: high. Confidence it recruits builders at volume: low (~15%).**

This deserves care, because it is the item most likely to be over- or
under-valued. It is real: screenreader mode, `WRAP_WIDTH = 0`, ANSI-aware width
measurement, and a maintainer whose own experience makes the commitment credible
in a way no competitor can manufacture. It earns goodwill, coverage, and a small
number of very loyal people.

But be honest about two things. First, **Evennia already claims this ground** —
"blind, accessible" are literal keywords in its PyPI metadata and it has a
long-standing screen-reader reputation. MegaMOO's edge is narrower than it feels
from inside. Second, accessibility recruits *players and advocates*, not
*builders*, and the stated goal is builders.

The right move is small and specific: make the **builder toolkit** accessible, not
just the player experience. Nobody has ever built a genuinely screen-reader-first
*world-building* environment. Twine is a visual node graph. Evennia's best
building tools are menus. If `@dig`/`@desc`/`@examine` plus a well-structured
`+show` is the most accessible authoring environment in game development, that is
a true, defensible, and *unclaimed* statement. Make it deliberately, then say it.

### 6. Discord interop
**Confidence: medium-high it works; ~50% it gets built. Best effort-to-payoff
ratio on the list.**

A bridge process that lets a world be played in a Discord channel is a few hundred
lines and puts a world where people already are. The pattern already exists — the
MCP bridge is a separate process with its own dependencies precisely so the engine
stays clean; a Discord bridge is the same shape against the same API. The honest
limit: MUD-in-a-chat-window is a mediocre play experience, so treat it as
*distribution and presence* (a world that idles in a server your friends are
already in), not as the primary client.

### 7. The browser as a *builder's* surface
**Confidence: medium (~35%).**

Going graphical for *players* is a losing fight — text games lose to graphical
games at being graphical, and the Orb Wars canvas renderer, while a nice proof,
is not a strategy. But **builders** in text gaming have essentially no visual
tooling. A live room-graph editor (drag a room, an exit is dug), an object
inspector, a verb editor with the docstring rendered as the help text it will
become — that is a place where the genre is genuinely deficient and where the
web client, `roommap.py`, and the API already give you most of the substrate.
Rank below the items above, but this is where "graphical" actually pays.

### 8. Teaching and education
**Confidence: low (~10%). The sentimental favourite and the worst ROI.**

MOO's educational niche died for reasons that have not reversed: Zoom took the
virtual-classroom job, Minecraft/Roblox/Scratch took the "kids build things" job,
institutional sales cycles are long and relationship-heavy, and there is no
budget. Add that you cannot let students program without a sandbox.

Do not target education. Do note that **if #2 and #3 land, education comes free**
as a consequence — fork a world per student, no sandbox needed, nothing to
install. Let it be a downstream effect, never a roadmap item.

### 9. LLM-driven world *generation*
**Confidence: low (~10%). Actively risky.**

Generating rooms and descriptions from a prompt is a demo, not a game.
Machine-generated worlds are the thing players most reliably notice and least
reliably enjoy, and the tooling to generate them is commodity. The valuable half
of this idea is already captured by #1 and by the MCP authoring loop, where the
model proposes and a **human reviews a diff**. Generation with a human in the
loop is D2. Generation without one is slop at scale.

### 10. Streaming / spectating
**Confidence: very low (~5%). Skip.**

Text is not watchable at scale. The successful text-game "streams" are actual-play
podcasts, which are a production format, not a platform feature.

### 11. Mobile
**Not innovation — hygiene.** "The web client is not broken on a phone" is table
stakes. A native app is a trap.

---

## 6. What to do first

Goal stated as: **more builders using it within a year.** Everything below is
ordered by that goal, not by interest.

### Monday: split the engine from the game

`pyproject.toml`. `pip install megamoo`. `megamoo init mygame` creating a game
directory the user owns and version-controls, with a documented place for
game-specific Python so nobody ever has to edit `moo/` again. Backfill by porting
`~/sfdev` onto it — if Shadowfall cannot run on the shipped engine, the split is
not done, and today it cannot.

This is first because nothing else compounds without it. A tutorial written before
the split teaches people to fork. A contrib written before the split has nowhere
to live. A hosted demo before the split is a snowflake. Every hour spent elsewhere
first is an hour spent on something that has to be redone.

### Week 2–3: credibility hygiene (one afternoon each, disproportionate return)

- Correct the line-count and web-client-size claims in the README.
- A GitHub Actions workflow running `pytest`. A green badge.
- A `Dockerfile` and a one-line `docker run` that lands you in a world.
- A tagged `v0.7.0` release with notes.
- `CONTRIBUTING.md`, a license note, an issue template.
- Publish the MCP bridge to PyPI so `claude mcp add megamoo` is one line.

None of this is interesting. All of it is what a builder checks in the ninety
seconds before deciding whether you are a real project.

### Month 2: one public world, one URL

An always-on instance of the web client with guest login, a small hand-built
world, and building enabled in a sandbox zone that resets nightly. Not a hosting
product — one demo you can put in a post. This is the single highest-leverage
marketing artifact the project can own, and the web client already does most of it.

### Month 2–4: world content as text (`@export` / `@import` for areas)

Symbolic references, readable files, round-trips through git. This is the
prerequisite for shareable areas (T2), for forkable worlds (#2), for content
testing, and for the entire differentiator story. Watch mooR while doing it.

### Month 3–5: content testing, using what already exists

A `VirtualConnection`, a scratch database, and hot reload are already in the tree.
A verb test should be about six lines: boot a world, connect a headless character,
send commands, assert on captured output. Then ship a small suite over the shipped
world so a contributor can change something and know they did not break `look`.
Inform 7 has had this for twenty years; it is table stakes and here it is nearly
free.

### Month 4–6: the tutorial, and the sentence

Write the beginner path — nothing to a room to an object to a verb to a friend
walking in — and write it *after* `megamoo init` exists so it teaches the right
shape. Put the positioning sentence on the front page: **multiplayer with IF-grade
authoring ergonomics, and no build step.**

### Month 6–12: the swing

Agent-as-inhabitant (#1), on top of a world that can now be exported, tested and
forked. Remove the single-TestBot lock, allow N agent characters, and build one
genuinely good agent NPC in the public demo world — one barkeep who is worth
talking to. One good NPC in a world anyone can visit will do more than a feature
list.

### Explicit traps — do not do these

| Trap | Why |
|---|---|
| A quest/dialogue DSL | Commodity, universally unloved, and Python verbs already do it better |
| Sandboxing CPython | Research problem, repeatedly lost; use forking or containers instead |
| Racing Evennia's 53 contribs | Unwinnable, and not why anyone would switch |
| A MOO-language interpreter | Head-on with mooR where they are strongest; `mooport`'s scope is correct |
| Graphical client for players | Text games lose at being graphical; go graphical for *builders* instead |
| Education outreach as a strategy | Long sales cycle, no budget, needs a sandbox; take it as a side effect |
| Multi-tenant hosting this year | Arbitrary Python execution as a service, with an ops bill |
| A native mobile app | Make the web client not break on a phone; stop there |
| Leading with "zero dependencies" | True, worth keeping, wins no arguments |

---

## Closing, unvarnished

MegaMOO is better-engineered than its adoption suggests — `roommap.py`,
`verb_baton.py`, the panel vocabulary, and the manual's prose are all above the
standard of the field. That is precisely why the diagnosis is uncomfortable: the
problems are not engineering problems, and the engineering instinct will want to
solve them with more engine. The engine is not the bottleneck.

The project is one week old in public with four stars, has no way to install it,
no way for a second person to build a game without forking it, no way to share
what they built, and nowhere to try it. Meanwhile Evennia has twelve years and
2,084 stars, and mooR is shipping the version-control story that is MegaMOO's
best differentiator idea. The window is open and it is not open indefinitely.

The good news is that the two hardest things are already done — a real MOO object
model, and a genuinely no-restart authoring loop — and the remaining work is
mostly packaging, plumbing, and one URL.
