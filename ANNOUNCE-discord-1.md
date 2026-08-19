# Long-time lurker, first-time show-and-teller. This all started here so it felt right to post it here.

A while back I built a full MOO platform on Evennia — the object model, the verb dispatch, the in-world programming, the lot. It worked, and I learned an enormous amount doing it. But I was fighting the grain: I wanted objects parented to other *objects*, editable from inside the game, and Evennia's inheritance lives in typeclasses — Python classes on disk. Not a flaw, a deliberate and sensible design — just not the MOO way, and I wanted the MOO way badly enough to stop working around it.

So I wrote one. **MegaMOO** — LambdaMOO's object model, with Python as the in-world language instead of MOO code.

```
pip install megamoo
megamoo init mygame
cd mygame && megamoo --dev
```

That last command prints a URL. Opening it drops you into the world — the browser client ships with the server, so there's nothing else to install and nothing to point at it.

- **Objects inherit from objects.** #17 is the parent of your rooms — edit it live, from inside the game, and every room changes.
- **Verbs are Python files.** One per verb. Edit in your editor and the running server picks it up; edit in-game with `@program` and the file is written for you. No reload, no restart.
- **Zero dependencies.** Standard library only — no Django, no ORM, no migrations. A real tradeoff: I gave up everything Django gives you for a server that's one process and one file.
- **A real browser client.** Text laid out on a terminal's character cell, so ASCII art and box drawing arrive the shape they were drawn rather than stretched into prose spacing. There's an automap built from the room graph, and you can drop a .png beside the ASCII intro to get a graphical splash screen instead.
- **SQLite object database**, TLS, MCCP2, MSSP.
