#!/usr/bin/env python3
"""
Regenerate the guide's command reference page from a world database.

The staff commands live on ``#3``, and everything the page shows is
already recorded there: the names, the abbreviation minimums, the
required level, and whether a command is hidden.  Reading them straight
out of the database means the page cannot drift from the commands it
documents -- which a hand-maintained table always eventually does.

What the database cannot supply is a readable one-line description, so
those live in :data:`GROUPS` below, together with the order and grouping
the page presents.  That is the part a person maintains.

Run it after adding, removing or re-levelling a staff command::

    python3 tools/gen_command_reference.py            # rewrite the page
    python3 tools/gen_command_reference.py --check    # just report drift

``--check`` writes nothing and exits non-zero if the page is out of date
or if a command has appeared that nobody has described yet, so it is
safe to wire into a pre-release check.

The database is opened read-only, so it is safe to run against a world
that is currently serving players.
"""

import argparse
import html
import json
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
#: The shipped starter world -- the one `megamoo init` copies, and so the
#: one whose commands the guide documents. This used to name mm.db, which
#: the starter template replaced; the tool then could not run without
#: --db, so nobody ran it, so the page drifted sixteen commands behind.
DEFAULT_DB = REPO_ROOT / 'moo' / 'templates' / 'starter' / 'world.db'
DEFAULT_OUT = REPO_ROOT / 'docs' / 'guide' / 'commands.html'

#: The page's meta description, stated once because it appears three
#: times in the head and a drifting copy is worse than none.
DESCRIPTION = (
    'Every command the shipped world ships with: the staff commands on #3 '
    'and the player commands on the room parents, with what each one does.'
)

#: The object staff commands are defined on.
STAFF_OBJECT = 3

#: Verbs on #3 that are machinery rather than commands: hooks called by
#: other code, which nobody can usefully type.  Listed so that a genuinely
#: new command still shows up as undescribed rather than being skipped.
NOT_COMMANDS = {'_allow', 'at_post_move', 'hands_free'}

#: Page structure: (anchor, heading, [(command, description)]).  Aliases
#: are mentioned inside the descriptions rather than given their own row.
GROUPS = [
    ('look', 'Looking at things', [
        ('+show', 'A quick summary of an object: its number, name, parent and location.'),
        ('@examine', 'Everything about an object — properties, verbs, tags, flags.'),
        ('+props', "List an object's properties."),
        ('+verbs', 'List the commands attached to an object.'),
        ('+decompile', "Print a verb's code exactly as stored — the ground truth for what is running."),
        ('@list', 'List objects in a range of numbers.'),
        ('+pron', 'Show the substitution tokens for messages (&amp;S, &amp;d and the rest).'),
        ('@find', 'Find objects anywhere in the database by name.'),
        ('@vfind', 'Find which objects define a command.'),
        ('@kids', 'List the objects that inherit from another.'),
        ('@grep', 'Search the source of every command for a string.'),
    ]),
    ('rooms', 'Rooms and exits', [
        ('@dig', 'Create a room. <code>@dig/types</code> lists the types, <code>@dig/tel</code> puts you in it.'),
        ('@vopen', 'A compass exit with no object behind it. The usual choice.'),
        ('@open', 'A compass exit as a real object, which can carry behaviour.'),
        ('@gopen', 'A named exit you walk through — a gate, an arch. A trailing direction (<code>@gopen door east</code>) is what lets the map draw it.'),
        ('@dopen', 'A door: it opens, closes and locks.'),
        ('@copen', 'A climbable exit — stairs, a ladder.'),
        ('@jopen', 'A jumpable exit — a gap or chasm.'),
        ('@rmexit', 'Remove an exit.'),
        ('@virtualize', 'Turn an exit object into a virtual one, keeping its messages.'),
        ('@coord', 'Say where a room is, so the map draws it there rather than deriving it. <code>@coord/fill</code> works outward from one room to the rest.'),
    ]),
    ('objects', 'Making and moving objects', [
        ('@make', 'Create an object from a prototype: <code>@make $item = sword</code>.'),
        ('@delete', 'Recycle an object.'),
        ('@move', 'Move an object somewhere else.'),
        ('@parent', 'Change what an object is built from.'),
        ('@renumber', 'Give an object a different number.'),
        ('@copy', 'Duplicate an object: same parent, name parts and local properties.'),
        ('@dump', 'Write an object out as text, to move or keep it.'),
        ('@load', 'Build an object from a file written by <code>@dump</code>.'),
    ]),
    ('naming', 'Naming and describing', [
        ('@name', 'Set the noun.'),
        ('@article', 'Set the article — <code>a</code>, <code>an</code> or <code>the</code>.'),
        ('@adjective', 'Set up to three adjectives. Give no value to clear them.'),
        ('@trailer', 'Set the text that follows the noun.'),
        ('@title', 'Rebuild the display name from its parts.'),
        ('@desc', 'Set what players read when they look at it.'),
    ]),
    ('messages', 'Action messages', [
        ('@success', 'What the person doing it sees.'),
        ('@osuccess', 'What everyone else in the room sees.'),
        ('@odrop', 'What the destination room sees on arrival.'),
        ('@failure', 'What the person sees when it does not work.'),
        ('@ofailure', 'What everyone else sees when it does not work.'),
        ('@drop', 'What the person sees on dropping it.'),
    ]),
    ('props', 'Properties and tags', [
        ('@adprop', 'Add a property that does not exist yet.'),
        ('@set', 'Change a property that already exists. Also <code>@val</code>.'),
        ('@unset', "Clear a property's value."),
        ('@rmprop', 'Remove a property.'),
        ('@remprop', 'Remove an override, falling back to what is inherited.'),
        ('@clear', "Clear a property or a verb's body."),
        ('@adtag', 'Add a tag: <code>@adtag room = zone/haven</code>.'),
        ('@rmtag', 'Remove a tag.'),
    ]),
    ('verbs', 'Commands', [
        ('@adverb', 'Create a command. <code>/hidden</code> makes it unreachable by typing.'),
        ('@program', "Open the editor for a command's code. Also <code>@prog</code>, <code>@code</code>."),
        ('@rmverb', 'Delete a command.'),
        ('@reload', 'Load a command from its file on disk.'),
        ('@min', 'Set how few letters will match the name.'),
        ('@verbauth', 'Set or read the level a command requires.'),
        ('@hideverb', 'Hide a command so nobody can type it.'),
        ('@unhideverb', 'Reverse that.'),
        ('@alias', "Show a command's names, or add one: <code>@alias #13.look = observe(3)</code>."),
        ('@rmalias', 'Remove one of those names, leaving the command itself.'),
    ]),
    ('numbers', 'Object numbers', [
        ('@fon', 'Release your reserved block, or with <code>/set</code>, <code>/list</code>, <code>/clear</code> manage it. Also <code>@freeon</code>.'),
        ('@foff', 'Reserve the unused numbers in your block. Also <code>@freeoff</code>.'),
        ('@reserve', 'Reserve a block outright; <code>/free</code> and <code>/list</code> too.'),
    ]),
    ('people', 'People and access', [
        ('@auth', 'Show what a player is authorised for, or grant it.'),
        ('@rmauth', 'Take an auth away, by `#obj = auth` or `auth from #obj`.'),
        ('@initchar', 'Give a character the full set of properties the game expects.'),
        ('@delplayer', 'Remove a player account.'),
        ('@tel', 'Teleport. Also <code>@telq</code>.'),
        ('hold', 'Hold an object in a specific hand.'),
        ('unhold', 'Stop holding it.'),
        ('@color', 'Show the colour palette.'),
        ('@rname', 'Rename an account, moving its login name with it.'),
        ('@audit', 'List everything a player owns.'),
        ('@quota', 'Report how much of the database a player has built.'),
    ]),
    ('server', 'Running the server', [
        ('@version', 'What the engine is, and what this world says it is. <code>@version/server</code> and <code>@version/db</code> ask separately.'),
        ('eval', 'Run Python against the live world. Also <code>/</code>.'),
        ('@restart', 'Restart in place.'),
        ('@shutdown', 'Stop the server.'),
        ('@ps', 'List the tasks the server is running.'),
        ('@kill', 'Abort a running or suspended task.'),
        ('@checkpoint', 'Take a database snapshot now, flushing memory to disk first.'),
        ('@port', 'Translate pasted MOO code into Python.'),
    ]),
]

GUARD_RE = re.compile(r'auth_level\(pobj\)\s*<\s*(\d+)')


def read_commands(db_path: Path) -> dict:
    """
    Read the staff commands out of *db_path*, keyed by every name.

    Returns:
        dict: name -> ``{'names', 'level', 'short', 'hidden'}``.

    Notes:
        The required level is the higher of two gates: the ``auth``
        column, which the engine checks before the verb body runs, and
        the ``auth_level(pobj) < N`` guard most staff verbs open with.
        A command is only as reachable as its stricter gate.
    """
    conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    try:
        rows = conn.execute(
            'select names, code, min_lengths, hidden, auth '
            'from verbs where objnum = ?', (STAFF_OBJECT,)).fetchall()
    finally:
        conn.close()

    commands = {}
    for raw_names, code, raw_mins, hidden, auth in rows:
        names = json.loads(raw_names or '[]')
        mins = json.loads(raw_mins or '{}')
        guard = GUARD_RE.search(code or '')
        level = max(int(auth or 0), int(guard.group(1)) if guard else 0)
        for name in names:
            minimum = mins.get(name) or 0
            commands[name] = {
                'names': names,
                'level': level,
                'short': name[:minimum] if minimum and minimum < len(name) else '',
                'hidden': bool(hidden),
            }
    return commands


def render(commands: dict) -> tuple:
    """
    Build the page, and report anything the description list has missed.

    Returns:
        tuple: ``(html_text, undescribed, vanished)`` -- the page, any
        command in the database that no group describes, and any
        described command no longer in the database.
    """
    described = {name for _, _, items in GROUPS for name, _ in items}
    aliases = {n for name in described if name in commands
               for n in commands[name]['names']}

    undescribed = sorted(
        name for name, c in commands.items()
        if name not in described and name not in aliases
        and name not in NOT_COMMANDS and not c['hidden'])
    vanished = sorted(name for name in described if name not in commands)

    sections = []
    for anchor, title, items in GROUPS:
        rows = []
        for name, desc in items:
            c = commands.get(name)
            if c is None:
                continue
            cell = f'<code>{html.escape(name)}</code>'
            if c['short']:
                cell += f' <span class="c">({html.escape(c["short"])})</span>'
            level = f'gm{c["level"]}' if c['level'] else '—'
            rows.append(f'<tr><td>{cell}</td><td><code>{level}</code></td>'
                        f'<td>{desc}</td></tr>')
        sections.append(
            f'<h2 id="{anchor}">{html.escape(title)}</h2>\n'
            '<div class="tablewrap">\n<table>\n'
            '<thead><tr><th>Command</th><th>Level</th><th>Does</th></tr></thead>\n'
            '<tbody>\n' + '\n'.join(rows) + '\n</tbody>\n</table>\n</div>\n')

    total = sum(1 for _, _, items in GROUPS
                for name, _ in items if name in commands)
    toc = '\n'.join(f'        <li><a href="#{a}">{html.escape(t)}</a></li>'
                    for a, t, _ in GROUPS)

    page = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Command Reference — MegaMOO Guide</title>
<!-- seo:begin -->
<meta name="description" content="{DESCRIPTION}">
<link rel="canonical" href="https://malifaxlax.github.io/megamoo/commands.html">
<meta property="og:type" content="website">
<meta property="og:site_name" content="MegaMOO">
<meta property="og:title" content="Command Reference — MegaMOO Guide">
<meta property="og:description" content="{DESCRIPTION}">
<meta property="og:url" content="https://malifaxlax.github.io/megamoo/commands.html">
<meta property="og:image" content="https://malifaxlax.github.io/megamoo/og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Command Reference — MegaMOO Guide">
<meta name="twitter:description" content="{DESCRIPTION}">
<meta name="twitter:image" content="https://malifaxlax.github.io/megamoo/og-image.png">
<link rel="icon" href="https://malifaxlax.github.io/megamoo/favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="https://malifaxlax.github.io/megamoo/apple-touch-icon.png">
<!-- seo:end -->
<link rel="stylesheet" href="manual.css">
</head>
<body>
<div class="wrap">

<p class="crumb"><a href="index.html">← MegaMOO Guide</a></p>

<h1 class="wordmark" style="font-size:clamp(1.8rem,6vw,2.4rem)">Command Reference</h1>
<p class="tagline">Every staff command, grouped by what it is for.</p>

<p>
The {total} commands below are attached to <code>#3</code>, so every character
inherits them. What you may actually use depends on your
<a href="verbs.html#auth">level</a> — the middle column. Without it, a command
answers <code>Do what?</code>, exactly as if it did not exist.
</p>

<p>
Where a short form is given in brackets, that is the fewest letters that will
match: <code>@art</code> reaches <code>@article</code>, and anything longer
works too.
</p>

<nav class="toc">
    <span class="kicker">Groups</span>
    <ol>
{toc}
    </ol>
</nav>

{chr(10).join(sections)}
<div class="note">
    <span class="label">Getting help on any of them</span>
    <p>Typing <code>help &lt;command&gt;</code> in the game prints that
       command's own documentation, which is the same text its author wrote —
       see <a href="help.html">The Help System</a>. This page is the map; the
       game itself has the detail.</p>
</div>

<div class="pagenav">
    <!-- living-world.html is the page that names this one as its Next; the
         footer said shops.html, which this guide has never had. -->
    <a href="living-world.html"><span class="dir">Previous</span>A World That Moves</a>
    <a class="to-next" href="moo-compat.html"><span class="dir">Next</span>Coming from LambdaMOO</a>
</div>

<div class="footer">
    <span><a href="index.html">← MegaMOO Guide</a></span>
    <span>Command Reference</span>
</div>

</div>
</body>
</html>
'''
    return page, undescribed, vanished


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    parser.add_argument('--db', type=Path, default=DEFAULT_DB,
                        help=f'world database to read (default: {DEFAULT_DB.name})')
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT,
                        help='page to write')
    parser.add_argument('--check', action='store_true',
                        help='report drift without writing; non-zero exit if any')
    args = parser.parse_args()

    if not args.db.exists():
        print(f'no such database: {args.db}', file=sys.stderr)
        return 2

    commands = read_commands(args.db)
    page, undescribed, vanished = render(commands)

    problems = False
    for name in undescribed:
        print(f'undescribed command (add it to GROUPS): {name}', file=sys.stderr)
        problems = True
    for name in vanished:
        print(f'described but no longer in the database: {name}', file=sys.stderr)
        problems = True

    current = args.out.read_text() if args.out.exists() else ''
    if args.check:
        if page != current:
            print(f'{args.out} is out of date', file=sys.stderr)
            problems = True
        elif not problems:
            print(f'{args.out} is up to date')
        return 1 if problems else 0

    if page == current:
        print(f'{args.out} already up to date')
    else:
        args.out.write_text(page)
        print(f'wrote {args.out}')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
