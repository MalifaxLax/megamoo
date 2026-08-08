"""
Takes a database checkpoint now.

Usage: @checkpoint

Switches:
    /list - Show the checkpoints that already exist, and create nothing.

Auth: gm4+ (auth_level 4)

Writes a consistent snapshot of the database to the checkpoint directory,
after flushing anything still only in memory.

Worth having as a command rather than only a timer, because the moments
you most want a snapshot are the ones no schedule knows about: before a
mass @set, before restarting into engine changes, before a bulk import.
The automatic checkpoint runs on its own clock and may be twenty minutes
away.

It is also what makes a copy of the live database trustworthy.  SQLite
keeps recent writes in a WAL sidecar and folds them into the main file
only at a checkpoint, so a `cp game.db elsewhere.db` taken at the wrong
moment produces a coherent *older* database rather than an obviously
broken one -- the worst kind of wrong.  Run this first and the main file
is current.

The snapshot is taken with SQLite's own backup, which reads through the
WAL and is safe against a live writer, so players need not be thrown off
first.  It does hold the verb baton while it runs, though, so the game
pauses for as long as the write takes -- a second or two on a small world,
longer on a large one.

Old checkpoints are pruned automatically; the most recent ten are kept.
"""

import os
import time

CHECKPOINT_GLOB = 'checkpoint_'


def _checkpoints(directory):
    """Existing checkpoint files, newest last, with their sizes."""
    try:
        names = sorted(n for n in os.listdir(directory)
                       if n.startswith(CHECKPOINT_GLOB) and n.endswith('.sqlite'))
    except OSError:
        return []
    out = []
    for n in names:
        path = os.path.join(directory, n)
        try:
            out.append((n, os.path.getsize(path)))
        except OSError:
            out.append((n, 0))
    return out


def _size(n):
    """Bytes as something a person can read."""
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return f'{n:.0f}{unit}' if unit == 'B' else f'{n / 1:.1f}{unit}'
        n /= 1024.0
    return f'{n:.1f}GB'


# The guard, not just the docstring.  The verb's auth value gates the
# command parser; this stops it being reached through call_verb, which
# the value does not cover.
if auth_level(pobj) < 4:
    pobj.msg('You are not authorized to do that.')
    return

directory = str(getattr(db, 'checkpoint_dir', '') or '')
if not directory:
    pobj.msg('This database has no checkpoint directory.')
    return

before = _checkpoints(directory)

if 'list' in switches:
    if not before:
        pobj.msg('&<245>No checkpoints yet.&n')
        return
    pobj.msg(f'&<245>{len(before)} checkpoint(s) in {directory}:&n')
    for name, size in before:
        pobj.msg(f'  {name}  &<245>{_size(size)}&n')
    return

pobj.msg('&<245>Saving and taking a snapshot -- the game pauses briefly.&n')

started = time.time()
try:
    db.checkpoint()
except Exception as err:
    pobj.msg(f'Checkpoint failed: {err}')
    return
elapsed = time.time() - started

# checkpoint() returns nothing, so the new file is found by comparing the
# directory rather than by being told -- which also catches the case where
# it silently did nothing, as it does in readonly mode.
after = _checkpoints(directory)
fresh = [c for c in after if c not in before]

if not fresh:
    pobj.msg('&<245>Nothing was written.  The database may be open '
             'read-only.&n')
    return

name, size = fresh[-1]
pobj.msg(f'  {name}  &<245>{_size(size)} in {elapsed:.1f}s&n')

pruned = len(before) + len(fresh) - len(after)
if pruned > 0:
    pobj.msg(f'  &<245>{pruned} old checkpoint(s) pruned; {len(after)} kept.&n')
