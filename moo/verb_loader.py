"""
Disk -> database verb loading helpers.
====================================

A verb's source of truth is the database (``mm.db``); the files under
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
from typing import Optional, List, Tuple

from moo.verbs import VerbDef

logger = logging.getLogger('megamoo.verb_loader')


def resolve_verb_base_path(db) -> Optional[str]:
    """
    Resolve ``#8.moo_verb_path`` to an absolute filesystem path.

    The property stores a dotted, home-relative path (e.g.
    ``"sfdev.moo verbs"``) which expands to ``~/sfdev/moo verbs``.

    Returns:
        The absolute path, or ``None`` if the property is unset.
    """
    verb_path = getattr(db.get_object(8), 'moo_verb_path', None)
    if not verb_path:
        return None
    return os.path.expanduser('~/' + verb_path.replace('.', '/'))


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
        return 'skipped'

    matches = [v for v in obj.verbs if verb_name in v.names]
    if matches:
        existing = matches[0]
        # Compile the candidate before touching the live verb so a syntax
        # error can never replace a working compiled body.
        candidate = VerbDef(
            names=list(existing.names),
            code=code,
            owner=existing.owner,
            perms=existing.perms,
            parent_type=existing.parent_type,
            min_lengths=dict(existing.min_lengths),
            hidden=existing.hidden,
            auth=existing.auth,
        )
        candidate.compile()  # raises CompileError -> caller logs, verb untouched
        existing.code = code
        existing.compiled_code = candidate.compiled_code
        obj._mark_modified()
        return 'updated'

    if not create:
        return 'skipped'

    new_verb = VerbDef(names=[verb_name], code=code, owner=obj.owner, perms='rx')
    new_verb.compile()  # validate before attaching; raises on syntax error
    obj.add_verb(new_verb)
    return 'created'
