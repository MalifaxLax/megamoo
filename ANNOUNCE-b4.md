Subject: MegaMOO 0.10.0b4 — the LambdaMOO model, with verbs in Python

I've been building MegaMOO, a text-world engine that takes MOO's object
model — objects carrying their own properties and verbs, single-parent
inheritance, live in-world programming, wizard/programmer/owner
permissions — and makes the in-world language Python instead of MOO.

    pip install megamoo
    megamoo init mygame
    cd mygame && megamoo --dev

Three commands and you're in a world you can build. Python 3.10+, no
dependencies at all — the engine runs on the standard library.

Guide: https://malifaxlax.github.io/megamoo/
Source: https://github.com/MalifaxLax/megamoo

On importing an existing MOO

I want to be straight about this because it's the first thing most MOO coders want to know.

I wrote an importer and ran it against Inferno, the MOO I ran from 1997 to 2010.
Its last database dump is 196MB; the import produced 61,009 objects and
3,337 verbs. It worked. I had Inferno in MegaMOO and I could walk around
in it.

It was just the wrong thing to do. The database was enormous, and most of
what came across was scaffolding rather than the world: utility objects,
editors, two quota systems, login, the help databases, the option
packages — all things MegaMOO already does in engine code. Measured
against stock LambdaCore, about seven verbs in ten are redundant before
translation even starts. What I'd actually imported was a second
implementation of my own server, sitting inside it.

And it changed what I was doing. Almost 200 verbs came across marked —
translated, but flagged as likely to run and mean the wrong thing — with
plenty more to patch up behind them. My time was going into making an
imported world viable instead of into the engine and building my game,
and that's not the project I want to be running.

So the importer isn't in the release. It exists and it works; I just don't think the thing it produces is worth having, and I'd rather say that than ship it and let people find out. If you think you can make the importer better or you've got a case I haven't thought of, I'd love for you to take a crack.

If what you want is your existing MOO code running unmodified, use mooR
(https://github.com/rdaum/moor) — a faithful LambdaMOO reimplementation
in Rust that imports LambdaMOO databases properly. That's the right tool
for that job and there's no sense in me building a worse one.

The half worth keeping is the world — rooms, things, descriptions, the
text somebody wrote by hand. That ports mechanically. The code half
mostly shouldn't come along.

@port

For code you do want to bring, there's a per-verb route rather than a
whole-database one: `@port <object>.<verb>` opens an editor ala @program, where you paste the MOO source, and it comes back as Python for you to review before it's saved. One verb at a time, with you looking at each result.

It needs a separate `mooport` package that isn't published yet. If that's
interesting to you, let me know — that's what would move it up the list.

What's new in 0.10.x

- **Installable.** `pip install megamoo` and `megamoo init` produce a game
  directory that belongs to you: your verbs, your world file, your git
  repo. The engine is a dependency, not something you fork. This is the
  change the whole 0.10 line exists for.
- **A browser client**, served by the game itself — one port covers the
  static files and the WebSocket. No separate web server.
- **TLS**, on a second port so telnet keeps working, and it refuses to
  start rather than quietly serving plaintext if you misconfigure it.
- **MCCP2 compression** — 56% fewer bytes on a measured session — and
  **MSSP**, so listing sites can poll you.
- Verbs are files on disk. Edit in your own editor and the running server
  picks it up; edit in-game with `@program` and the file is written for
  you.

Bugs

b0 through b3 shipped a starter world with real problems in it — you
couldn't pick stuff up, chargen died partway, and every character
introduced itself by the name of its prototype. All fixed in b4, along
with a batch of others. If you tried an earlier beta and it fell over,
it wasn't you.

It is beta and it is one person's project. Lots of rough edges, and
I'd rather hear about them than not.


Questions

GitHub Discussions is the place — answers there stay public and
searchable, which matters more than it sounds for a small project:
https://github.com/MalifaxLax/megamoo/discussions

There's a Discord too, for chat: https://discord.gg/E74YsbbpCA

Happy to answer here as well.

— Shan
