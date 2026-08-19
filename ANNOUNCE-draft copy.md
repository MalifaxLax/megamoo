# Long-time lurker, first-time show-and-teller. This all started here for me, so...

I built a full MOO platform on top of Evennia a while back, the object
model, the verb dispatch, the in-world programming, everything. It worked,
and I learned a whole lot doing it. But I was constantly battling opposing
paradigms. I wanted objects parented to other *objects*, editable from
inside the game, and Evennia's inheritance lived in typeclasses. Not a
flaw, a deliberate and sensible design — just not the MOO way, and I wanted
the MOO way badly enough to stop trying to work around it.

So I wrote **MegaMOO** — LambdaMOO's object model, with Python as the
in-world scripting language instead of MOO code.

I couldn't have done it without Evennia's inspiration though, and help from
the Inspector and scads of others who constantly and patiently answered my
questions, so I mostly want to say thanks. Griatch, your work is why I
understood what a MUD engine even looks like from the inside, and the
reason I thought building one was something a person could even do. A lot
of MegaMOO's shape is me seeing the decisions you made for Evennia and then making my own design decisions for a modern MOO-based world-building platform using everything I learned from you.

But MegaMOO is not Evennia. I decided early on that I wanted no third party
dependencies, no Django, no ORM, no migrations, and that's a real
trade-off. MegaMOO has none of the rich, built-in Django infrastructure
that Evennia offers. I just wanted a simple MOO server that's one process
and one file, and that's the direction I went.

## What MegaMOO is

- **Objects inherit from objects.** `#17` is the parent of every room in
  your world. Edit it live, from inside the game, and every room updates.
  No file, no restart, no deploy — the thing I couldn't stop wanting.

- **Verbs are Python files.** One per verb. Edit in your editor and the
  running server picks it up; edit in-game with `@program` and the file is
  written for you and loaded hot. No reload, no restart.

- **A built-in browser client** Served by the game
  itself, over the same world telnet players are in. It lays text out on a
  terminal's character cell, so ASCII art and box drawing arrive the shape
  they were drawn rather than stretched into prose spacing. There's a basic
  automapper built from the room graph, and a world can drop a PNG beside its
  ASCII intro and get a splash screen instead.
  
  - **Players can script it, without installing anything.** The client has
  the backslash commands you'd expect — aliases, triggers, saved worlds —
  and for anything more, players write their own in **Lua or JavaScript**
  from a Scripts button. Both get an identical API, so logic ports between
  them: trigger on output, claim input before it's sent, timers, persistent
  per-script storage, GMCP subscriptions, and `moo.panel()` to put a
  heads-up display on the screen.

- **The world is built from inside.** `@dig`, `@vopen`, `@make`,
  `@desc`, `@program` — rooms, exits, objects and behaviour, all from the
  command line you play on. Nothing needs a text editor, though everything
  is a file if you want one.

- **Per-object behaviour without subclassing.** A room's `get`command calls get_` on whatever you reached for, so one object can answer differently
  from every other object of its kind, and you write that where the object
  is rather than in a class module.

- **SQLite object database, TLS, MCCP2, MSSP.**

## Trying it
```
pip install megamoo
megamoo init mygame
cd mygame && megamoo --dev

That last command prints an URL. Opening it puts you in the world — the
browser client ships with the server, so there's nothing else to install.

MegaMOO 0.10 beta and it's one person, so temper expectations accordingly.
But it runs, it's documented, and I'd genuinely like to know what you
think.

<https://malifaxlax.github.io/megamoo/>
