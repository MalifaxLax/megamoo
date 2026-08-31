Hello! Long-time lurker here, first-time show-and-teller. This all started here for
me, so...

I built a full MOO platform on top of Evennia a while back, and it worked,
and I learned a ton doing it. But I was constantly battling opposing
paradigms and that got really tedious. I wanted objects parented to other
*objects*, editable on the fly from inside the game, and Evennia's
inheritance lived in typeclasses. Not a flaw, a deliberate and sensible
design — just not the MOO way, and I wanted the MOO way badly enough to
stop working around it.

So I wrote MegaMOO — LambdaMOO's object model, with Python as the in-world scripting language instead of MOO code...

I couldn't have done it without Evennia's inspiration though, and help
from the Inspector and scads of others who patiently answered my
questions, so I mostly want to say thanks. The Evennia community is
amazing.

Griatch, your work is why I understood what a MUD engine even looks
like from the inside, and the reason I believed building one was
something a guy like me could even do. A lot of MegaMOO's shape is me
seeing the decisions you made for Evennia and then making my own design
decisions for a modern MOO-based world-building platform using
everything I learned from you.

But MegaMOO is not Evennia. I decided early on that I wanted no third
party dependencies, no Django, no ORM, no migrations, and that's a real
trade-off. MegaMOO has none of the rich, built-in Django infrastructure
that Evennia offers. I just wanted a simple MOO server that's one
process and one file, and that's the direction I went.

A few highlights:

Prototypal inheritance: objects inherit from other objects rather than
from classes.

Verbs are Python files, one per. Edit in your editor and the running
server picks it up; edit in-game with @code and the file is written for
you and loaded hot. No reload, no restart.

Built-in browser client served by the game itself, with an automapper
built from the room graph — or from coordinates you set yourself, when
you want the map exactly right rather than merely plausible. Drop a PNG
beside the ASCII intro and get a graphical splash screen instead.

Player client scripting. The client has the backslash commands you'd
expect — aliases, triggers, saved worlds — and for anything more,
players write their own in Lua or JavaScript.

Per-object behaviour without subclassing. Each command calls verb_name_
on a matched object, so one object can answer differently from every
other of its kind, written as an object method rather than in a class
module.

Under the hood — SQLite object database with WAL crash recovery, telnet
and browser players in the same process, MXP links, GMCP, MSSP, MCCP2,
TLS, and a JSON API that reads and writes a running world from outside,
which is what an MCP server or an AI agent talks to.

Multiple worlds spun up and running simultaneously. Just copy and start.

And my personal favorite, a '/' aliased eval command that parses
ordinals and adjective-object strings as well as object numbers:

    /2 velvet drape.behind_exit = #5010

Trying it out:

pip install megamoo
megamoo init mygame
cd mygame && megamoo --dev

That last command prints a URL. Opening it puts you in the world — the
browser client ships with the server, so there's nothing else to
install.

MegaMOO is at 0.10.0-beta16 and it's one person, so temper your
expectations accordingly. It runs though, it's documented, and I'd
genuinely like to know what you think.

<https://malifaxlax.github.io/megamoo/>

I'm building a MegaMOO-based game myself, old-school hack & slash with
an emphasis on role-play and mechanics built to encourage and reward
player interaction, cooperation and collaboration. Swords, sorcery and cybernetics in a mutating post-apocalyptic world. A few screenshots:
