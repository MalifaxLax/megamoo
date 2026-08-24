"""
Disk -> database verb loading helpers.
====================================

A verb's source of truth is the database (``sf.db``); the files under
``<moo_verb_path>/<objnum>/<verbname>.py`` are developer-facing copies that
make it convenient to edit verb code in a real editor.  These helpers read a
disk file and push it into the live in-memory object, recompiling and marking
the object modified so the change persists at the next checkpoint.

Two callers share this module so they stay in lock-step:

* the ``@reload`` wizard verb (``moo verbs/3/@reload.py``), invoked manually;
* the optional auto-reload watcher (:meth:`moo.server.MegaMOOServer._watch_verbs`),
  which polls the verb tree and hot-loads edits while the server runs.

Safety contract
---------------
:func:`reload_verb_code` compiles the *new* source in isolation **before**
touching the live verb.  Only if that compile succeeds are ``code`` and
``compiled_code`` committed onto the existing :class:`~moo.verbs.VerbDef`.
A syntax error therefore leaves the previously-working verb untouched -- the
command path (which recompiles from ``verb_def.code`` on every call) keeps
serving the old, good code rather than erroring out for players.
"""
import os
import logging
import re
from typing import Optional, List, Tuple

from moo.verbs import VerbDef
from moo.verb_meta import parse_verb_meta

logger = logging.getLogger('megamoo.verb_loader')

# ``if auth_level(pobj) < 3:`` -- the guard staff verbs open with.
_AUTH_GUARD_RE = re.compile(
    r'auth_level\(\s*(?:pobj|player)\s*\)\s*(<=?)\s*(\d+)')

#: ``Auth: gm4+ (auth_level 4)`` -- the line every staff verb's docstring
#: carries.  Only consulted when there is no guard to read instead.
_AUTH_DOC_RE = re.compile(r'auth_level\s+(\d+)\s*\)')


def auth_level_required(code: str) -> int:
    """
    The gm level *code* refuses to run below, read from its own guard.

    A staff verb states its level twice: an ``auth_level(pobj) < N`` guard
    that actually enforces it, and an ``auth`` value on the verb that
    ``help`` filters the command list with.  A verb created from disk used
    to get the guard and not the value, so ``help`` advertised it to
    players who could not run it and it answered "Do what?" -- the bug
    that started the MOO-compatibility work.  Deriving the value from the
    guard keeps the two in step without anyone having to remember.

    A verb may hold several guards: a low bar to run at all and a higher
    one for a privileged switch.  The lowest is returned, since that is
    the level at which the command becomes usable and therefore worth
    listing.

    A verb that *documents* a level but has no guard falls back to the
    documented one, and says so.  That case is a mistake -- the guard is
    what stops a privileged verb being reached through call_verb, and the
    value only filters the command list -- but publishing it at 0 because
    the author forgot is the worse of the two failures: it makes a wizard
    command runnable by anyone the moment the file lands on disk.  This is
    not hypothetical; @checkpoint shipped that way for several minutes.

    Returns 0 when there is neither, which is right for player commands
    and for hooks.
    """
    levels = []
    for op, num in _AUTH_GUARD_RE.findall(code or ''):
        n = int(num)
        levels.append(n if op == '<' else n + 1)
    if levels:
        return min(levels)

    documented = _AUTH_DOC_RE.search(code or '')
    if documented:
        level = int(documented.group(1))
        logger.warning(
            'verb documents auth_level %d but has no auth_level() guard; '
            'gating dispatch at %d, but the verb is still reachable through '
            'call_verb -- add the guard', level, level)
        return level
    return 0


def resolve_verb_base_path(db) -> Optional[str]:
    """
    Resolve ``#8.moo_verb_path`` to an absolute filesystem path.

    The property stores a dotted, home-relative path (e.g.
    ``"sfdev.moo verbs"``) which expands to ``~/sfdev/moo verbs``.

    Returns:
        The absolute path, or ``None`` if the property is unset.
    """
    from .object_utils import system_ref
    verb_path = system_ref(db, 'moo_verb_path')
    if not verb_path:
        holder = system_ref(db, 'config', fallback_objnum=8)
        verb_path = getattr(holder, 'moo_verb_path', None)
    if not verb_path:
        return None
    return expand_verb_path(verb_path)


def expand_verb_path(verb_path: str) -> str:
    """
    Turn a stored verb-tree location into an absolute path.

    Two forms, because the old one cannot be dropped and should not be
    inflicted on anybody new.

    An ordinary path is used as an ordinary path: absolute, or starting
    with ``~``, or containing a separator.  ``/opt/world/verbs`` means
    that.

    Anything else is read the old way -- dotted and relative to the home
    directory, so ``"sfdev.moo verbs"`` is ``~/sfdev/moo verbs``.  That
    spelling came from ``#8.moo_verb_path`` being a Python-ish module path
    and is why an absolute path used to silently become ``~//opt/...``,
    and why a directory with a dot in its name broke.

    Args:
        verb_path: Whatever the database stores.

    Returns:
        An absolute filesystem path.
    """
    text = str(verb_path).strip()
    if text.startswith(('/', '~')):
        return os.path.abspath(os.path.expanduser(text))
    if os.sep in text:
        # Relative, but written as a path.  Anchored at home rather than
        # at the working directory: this is a stored value and the
        # directory a server happens to be started from is not something
        # the database should depend on.
        return os.path.expanduser('~/' + text)
    return os.path.expanduser('~/' + text.replace('.', '/'))


def is_blank_verb_file(code: str) -> bool:
    """True if *code* has no meaningful (non-comment, non-blank) lines."""
    meaningful = [
        line for line in code.splitlines()
        if line.strip() and not line.strip().startswith('#')
    ]
    return not meaningful


def scan_verb_files(base_path: Optional[str]) -> List[Tuple[int, str, str]]:
    """
    Walk ``<base_path>/<objnum>/<name>.py`` and list every verb file.

    Only numeric sub-directories are considered (matching the per-object
    layout that ``@reload`` exports).  The flat fallback files directly
    under ``base_path`` are intentionally ignored: without an object number
    we cannot know where to load them.

    Returns:
        A list of ``(objnum, verb_name, filepath)`` tuples, sorted.
    """
    results: List[Tuple[int, str, str]] = []
    if not base_path or not os.path.isdir(base_path):
        return results
    for entry in sorted(os.listdir(base_path)):
        obj_dir = os.path.join(base_path, entry)
        if not entry.isdigit() or not os.path.isdir(obj_dir):
            continue
        objnum = int(entry)
        for fname in sorted(os.listdir(obj_dir)):
            if fname.endswith('.py'):
                results.append((objnum, fname[:-3], os.path.join(obj_dir, fname)))
    return results


def reload_verb_code(obj, verb_name: str, code: str, *, create: bool = True) -> str:
    """
    Push *code* onto *verb_name* of *obj*, recompiling.

    The new source is compiled in isolation first; the live verb is only
    mutated once that compile succeeds (see the module-level safety contract).

    Args:
        obj: The :class:`~moo.objects.MOOObject` carrying the verb.
        verb_name: Name to match against existing verbs / use for a new one.
        code: New verb source read from disk.
        create: If ``True`` and no verb matches, create a new ``rx`` verb.

    Returns:
        One of ``'updated'``, ``'created'`` or ``'skipped'`` (blank file, or
        no match with ``create=False``).

    Raises:
        CompileError: If *code* fails to compile.  The live verb is left
            untouched in this case.
    """
    if is_blank_verb_file(code):
        # A blank file is not an empty verb, it is no opinion at all -- so
        # its metadata is not read either and the database keeps what it
        # holds.
        return 'skipped'

    # What the file says about itself.  Disk is authoritative here for the
    # same reason it is for the code: the tree is what git tracks, and a
    # tree that cannot describe an alias is one a world cannot be rebuilt
    # from.  See moo.verb_meta.
    meta = parse_verb_meta(code, verb_name)

    matches = [v for v in obj.verbs if verb_name in v.names]
    if matches:
        existing = matches[0]
        # Compile the candidate before touching the live verb so a syntax
        # error can never replace a working compiled body.
        candidate = VerbDef(
            names=list(meta['names']),
            code=code,
            owner=existing.owner,
            perms=meta['perms'],
            parent_type=meta['parent_type'],
            min_lengths=dict(meta['min_lengths']),
            hidden=meta['hidden'],
            auth=existing.auth,
        )
        candidate.compile()  # raises CompileError -> caller logs, verb untouched
        # Abbreviations are part of what the cache stores: matchable_names()
        # is built from names *and* min_lengths, so editing `examine=3` to
        # `examine=2` with the names untouched left every descendant still
        # matching only `exa`, and a removed abbreviation went on answering
        # until something unrelated happened to invalidate the cache.
        renamed = (list(existing.names) != list(meta['names'])
                   or dict(existing.min_lengths) != dict(meta['min_lengths']))
        existing.code = code
        existing.compiled_code = candidate.compiled_code
        existing.names = list(meta['names'])
        existing.min_lengths = dict(meta['min_lengths'])
        existing.hidden = meta['hidden']
        existing.perms = meta['perms']
        existing.parent_type = meta['parent_type']
        obj._mark_modified()
        if renamed:
            # A name cached under the old set would go on answering, or
            # stop answering, until something else happened to invalidate
            # it.  Verb lookup is cached per object and inherited by every
            # descendant, so this has to propagate.
            try:
                obj.invalidate_inheritance_cache()
            except Exception:      # pragma: no cover - best effort
                pass
        return 'updated'

    if not create:
        return 'skipped'

    # Derive auth from the verb's own guard.  Without this a staff verb
    # arrives with auth 0, help advertises it to players who cannot run it,
    # and it answers "Do what?" when they try.  Existing verbs keep whatever
    # auth they already have -- that is handled above, and may have been set
    # deliberately with @verbauth.
    new_verb = VerbDef(names=list(meta['names']), code=code, owner=obj.owner,
                       perms=meta['perms'], min_lengths=dict(meta['min_lengths']),
                       hidden=meta['hidden'], auth=auth_level_required(code),
                       parent_type=meta['parent_type'])
    new_verb.compile()  # validate before attaching; raises on syntax error
    obj.add_verb(new_verb)
    return 'created'
