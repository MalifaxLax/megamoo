#!/usr/bin/env python3
"""
Fold a tracked SQLite database's WAL into the file before it is committed.

Git commits the *file*. SQLite, in WAL mode, does not put every committed
write in the file -- a reader sees committed WAL content, so the database
answers correctly while the file on disk is behind. The two are different
questions and only one of them is what git stores.

The failure that follows is quiet and convincing: you edit a starter verb,
save the world, read it back to confirm, commit both, and ship a
`world.db` without the change. Nothing warns you. The verb file in the
commit and the database in the commit disagree, and the repository's own
convention -- a changed `moo/templates/starter/verbs/**` file and
`moo/templates/starter/world.db` land in the same commit -- is what makes
that disagreement matter: `megamoo init` hands the mismatch to a new user.

Every TRACKED database, not merely the staged ones -- and that distinction
is the whole point. A database whose writes are all still in the WAL has
an unmodified *file*, so `git status` reports nothing, so it never gets
staged, so a hook that only looks at staged files never runs. Looking only
at what was staged would inspect nothing and report success.

PASSIVE rather than TRUNCATE because a live server usually holds the
database -- passive does what it can without waiting on readers, which is
enough to move committed frames into the file.

A database that was already staged is re-staged silently. One that was not
staged but changed is reported and left alone: quietly adding a file to a
commit the author did not ask for is its own kind of surprise, and the
warning is enough to act on.

A database this cannot open is left alone and reported rather than
blocking the commit: not every `.db` is SQLite, and a hook that refuses to
let you commit is worse than one that tells you what it skipped.

Exit status is always 0. This is a correctness convenience, not a gate.

Install the hook with `python3 tools/checkpoint_dbs.py --install`; run it
with no arguments to checkpoint by hand. `.git/hooks/` is not tracked, so
a fresh clone starts without the guard and has to install it once.
"""
import hashlib
import os
import subprocess
import sqlite3
import sys

# Extensions worth looking at. `.db` is what the starter world uses; the
# rest cost nothing to check and mean the guard is already in place on the
# day someone tracks a database named the other way.
SUFFIXES = ('.db', '.sqlite', '.sqlite3')

HOOK = '''#!/bin/sh
# Fold any tracked SQLite database's WAL into the file before committing.
# See tools/checkpoint_dbs.py for why this exists, and re-run
# `python3 tools/checkpoint_dbs.py --install` in a fresh clone.
#
# .git/hooks is shared by every worktree, while the script it runs is
# tracked and so exists only on branches that carry it. A worktree without
# it commits normally instead of failing on a missing file -- blocking a
# commit is exactly what this guard is not for.
guard="$(git rev-parse --show-toplevel)/tools/checkpoint_dbs.py"
[ -f "$guard" ] || exit 0
exec python3 "$guard"
'''


def _git(*args):
    """Run a git command at the repository root and return its stdout."""
    return subprocess.run(('git',) + args, capture_output=True, text=True,
                          check=False).stdout


def repo_root():
    """The working tree's top level, or None outside a repository."""
    root = _git('rev-parse', '--show-toplevel').strip()
    return root or None


def _digest(path):
    """Content hash -- the only reliable "did this file change" here."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def tracked_databases():
    """Every tracked database, staged or not, relative to the repo root.

    `--full-name` because the starter world is nested several directories
    down: paths have to be root-relative to be worth staging, whatever
    directory the caller happened to be in.
    """
    patterns = ['*%s' % suffix for suffix in SUFFIXES]
    out = _git('ls-files', '--full-name', '--', *patterns)
    return [line for line in out.splitlines() if line.endswith(SUFFIXES)]


def staged_databases():
    """The subset already staged for this commit."""
    out = _git('diff', '--cached', '--name-only', '--diff-filter=ACM')
    return {line for line in out.splitlines() if line.endswith(SUFFIXES)}


def checkpoint(path):
    """Fold *path*'s WAL into the file. Returns a status string."""
    if not os.path.exists(path):
        return 'missing'
    try:
        db = sqlite3.connect(path)
    except sqlite3.Error as e:
        return f'not openable ({e})'
    try:
        busy, written, moved = list(db.execute('pragma wal_checkpoint(PASSIVE)'))[0]
    except sqlite3.Error as e:
        return f'checkpoint failed ({e})'
    finally:
        db.close()
    if written < 0:
        # Not in WAL mode at all, which SQLite reports as -1 rather than 0.
        # Nothing is ever held back from the file in that mode, so there is
        # nothing here to fold -- and saying "folded -1 frame(s)" about a
        # database that is fine would send someone looking for a problem.
        return 'not in WAL mode'
    if busy:
        return f'BUSY -- {written} frame(s) left in the WAL'
    return 'clean' if written == 0 else f'folded {written} frame(s)'


def hooks_dir():
    """Where this repository actually looks for hooks.

    The common git dir rather than `--git-dir`: a linked worktree's git dir
    holds no hooks of its own, and installing there would write a hook git
    never runs. `core.hooksPath` wins if someone has set it.
    """
    configured = _git('config', '--get', 'core.hooksPath').strip()
    if configured:
        return os.path.abspath(os.path.expanduser(configured))
    common = _git('rev-parse', '--git-common-dir').strip() or '.git'
    return os.path.abspath(os.path.join(common, 'hooks'))


def install():
    """Write .git/hooks/pre-commit. Returns a process exit status."""
    directory = hooks_dir()
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, 'pre-commit')

    if os.path.exists(path):
        with open(path) as f:
            existing = f.read()
        if 'checkpoint_dbs.py' not in existing:
            print(f'{path} already exists and is not this guard; leaving it '
                  f'alone.\nMerge it by hand -- the hook is four lines, in '
                  f'the HOOK constant of {__file__}.', file=sys.stderr)
            return 1
        if existing == HOOK:
            print(f'Already installed: {path}')
            return 0

    with open(path, 'w') as f:
        f.write(HOOK)
    os.chmod(path, 0o755)
    print(f'Installed: {path}')
    return 0


def main(argv):
    root = repo_root()
    if root is None:
        print('Not a git repository; nothing to checkpoint.', file=sys.stderr)
        return 0
    # Git runs hooks from the top of the working tree, but a person running
    # this by hand is wherever they are. Both need root-relative paths for
    # `git add` to name the right file.
    os.chdir(root)

    if '--install' in argv:
        return install()

    paths = tracked_databases()
    if not paths:
        return 0
    staged = staged_databases()
    for path in paths:
        if not os.path.exists(path):
            continue
        before = _digest(path)
        status = checkpoint(path)
        changed = _digest(path) != before

        if path in staged:
            # Re-stage unconditionally rather than only when the file
            # changed. Correctness here must not depend on detecting a
            # change -- mtime granularity and SQLite's own writes make
            # that unreliable, and re-adding an identical file costs
            # nothing. This is the path that keeps a commit honest.
            subprocess.run(['git', 'add', '--', path], check=False)
            status += ', re-staged'
        elif changed:
            status += (' -- NOT in this commit; `git add %s` if the world '
                       'should be part of it' % path)

        if changed or path in staged:
            print(f'  [checkpoint] {path}: {status}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
