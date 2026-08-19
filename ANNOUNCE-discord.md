# Long-time lurker, first-time show-and-teller. This all started here so it felt right to post it here.

A while back I built a full MOO platform on Evennia. It worked, and I learned a lot, but I was fighting the grain. I wanted objects parented to other objects*, editable from inside the game and Evennia's inheritance lived in typeclasses on disk. Not a flaw, a deliberate design — just not the MOO way, and I wanted the MOO way badly enough to stop working around it.

So I wrote one. **MegaMOO** — LambdaMOO's object model, with Python as the in-world language instead of MOO code.

```
pip install megamoo
megamoo init mygame
cd mygame && megamoo --dev
```

That last command prints a URL that drops you into the world; the browser client ships with the server.

- **Objects inherit from objects.** #17 is the parent of your rooms — edit it live, in-game, and every room changes.
- **Verbs are Python files.** Edit in your editor and the running server picks it up; edit in-game with `@program` and the file is written for you. No restart.
- **Zero dependencies.** Standard library only — a real tradeoff, but the server is one process and one file.
- **A real browser client.** Text on a terminal's character cell, so ASCII art arrives the shape it was drawn. Drop a .png beside the ascii intro and get a graphical splash screen instead- 
- **SQLite object database**, TLS, MCCP2, MSSP.

To be clear: 0.10 beta, one person, and Evennia is vastly more capable and better supported, a narrower thing, for people who want the MOO model.

One caveat up front: `megamoo init` hands you a copy of the starter world, and from then on it's yours. Improvements I make later don't find their own way in. Verb files carry across by hand; database changes don't yet. Still growing into shape, though: beta13 records which release a world was built from.

Mostly, thanks. Griatch, your work is why I understood what a MUD engine looks like from the inside, and why I thought building one was something a person could do.

#### https://malifaxlax.github.io/megamoo/
