"""
The file builtins an Inferno-style server adds, confined to one directory.

LambdaMOO has no file access.  Servers that wanted it added it, and the
shape Inferno uses is a small line-oriented API where every call names a
*directory* and a *file* separately::

    fileread("admin", "info")            -> the file's lines
    fileappend("inferno", "PvPLog", {…}) -> add lines to the end
    filelist("inferno/npcs")             -> {files, directories}

That split is not decoration.  Neither half is ever an absolute path, so
the whole API is relative to a root by construction -- which is what makes
it safe to implement here.

Why this is sandboxed rather than passed through
------------------------------------------------

The verb sandbox already allows ``import`` and ``open``, so on the face of
it these functions add nothing a verb could not do anyway.  The reason to
write them properly is the opposite of adding capability: **importing
somebody else's core should not hand their verbs your filesystem.**

A ported core arrives with thousands of verbs nobody has read.  Inferno's
own use is innocuous -- logs, news, guild data, saved NPCs -- but the
importer cannot know that of an arbitrary database, and "it only touches
files under one directory you chose" is a claim worth being able to make.

So every path is resolved against :func:`files_root` and checked to be
inside it after resolution, which is what catches ``..`` and symlinks
rather than trusting the string.

Line numbering
--------------

MOO counts from one, and these are line-oriented, so ``filewrite``'s
*start* is a 1-based line number and ``filelist`` returns ``{files,
dirs}`` read as ``[1]`` and ``[2]``.  The conversions live here rather
than in the translator, because @port shifts *subscripts* and these are
arguments.
"""

import logging
import os
import shutil
from typing import List, Optional

from .properties import MOOError

logger = logging.getLogger('megamoo.files')

__all__ = [
    'files_root', 'set_files_root',
    'fileread', 'filewrite', 'fileappend', 'filelist', 'filedelete',
    'fileexists', 'filelength', 'filemkdir', 'filermdir', 'filerename',
]

#: Where the file builtins are allowed to work.  None means they are
#: switched off, which is the default: a server that has not been told
#: where to put these files has not agreed to have them.
_ROOT: Optional[str] = None


def set_files_root(path: Optional[str]) -> None:
    """
    Point the file builtins at a directory, or switch them off.

    Args:
        path: The directory they may work inside, or None to disable.
    """
    global _ROOT
    _ROOT = os.path.realpath(path) if path else None
    if _ROOT:
        os.makedirs(_ROOT, exist_ok=True)
        logger.info('file builtins enabled, rooted at %s', _ROOT)
    else:
        logger.info('file builtins disabled')


def files_root() -> Optional[str]:
    """The directory the file builtins are confined to, or None."""
    return _ROOT


def _resolve(directory, filename=None) -> str:
    """
    The real path for a MOO (dir, file) pair, inside the root.

    Args:
        directory: The directory part, relative to the root.
        filename: The file part, or None for a directory operation.

    Returns:
        An absolute path that is provably inside the root.

    Raises:
        MOOError: If the file builtins are switched off, or the path
            escapes the root.  The check is on the *resolved* path rather
            than the string, so ``..`` and symlinks are both caught -- a
            string check would pass ``a/../../etc`` and a symlink would
            defeat it entirely.
    """
    if _ROOT is None:
        raise MOOError('file builtins are not enabled on this server; '
                       'set a files root to turn them on')
    parts = [str(directory or '')]
    if filename is not None:
        parts.append(str(filename))
    # An absolute path is contained anyway -- the strip below turns
    # "/etc" into "etc", so it lands under the root -- but silently
    # reading root/etc/passwd when a verb asked for /etc/passwd is a
    # confusing way to be safe.  Refusing says what happened.
    for part in parts:
        if part.startswith('/'):
            raise MOOError(f'{part}: absolute paths are not allowed; '
                           f'these builtins work inside the files root')
    joined = os.path.join(_ROOT, *[p.strip('/') for p in parts if p])
    real = os.path.realpath(joined)
    if real != _ROOT and not real.startswith(_ROOT + os.sep):
        raise MOOError(f'{directory}/{filename}: outside the files root')
    return real


def fileread(directory, filename) -> List[str]:
    """
    Inferno's ``fileread()``: a file's lines.

    Args:
        directory: Directory, relative to the files root.
        filename: File within it.

    Returns:
        list: The lines, without terminators.  A file that is not there
        reads as empty rather than raising, which is what the callers
        expect -- they test the result for emptiness.
    """
    path = _resolve(directory, filename)
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            return fh.read().splitlines()
    except FileNotFoundError:
        return []
    except OSError as err:
        raise MOOError(f'fileread({directory}, {filename}): {err}')


def filewrite(directory, filename, lines, start=None, count=None) -> int:
    """
    Inferno's ``filewrite()``: replace a file, or a run of lines in it.

    With three arguments the file becomes *lines*.  With five, *count*
    lines starting at *start* are replaced by *lines* -- which is how the
    callers delete a range, by passing an empty list.

    Args:
        directory: Directory, relative to the files root.
        filename: File within it.
        lines: The lines to write.
        start: 1-based line to start replacing at.
        count: How many lines to replace.

    Returns:
        int: 1 on success.
    """
    path = _resolve(directory, filename)
    lines = [str(x) for x in (lines or [])]
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if start is None:
            body = lines
        else:
            try:
                with open(path, 'r', encoding='utf-8', errors='replace') as fh:
                    body = fh.read().splitlines()
            except FileNotFoundError:
                body = []
            i = max(0, int(start) - 1)          # MOO counts from one
            n = len(body) if count is None else max(0, int(count))
            body = body[:i] + lines + body[i + n:]
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(body))
            if body:
                fh.write('\n')
        return 1
    except OSError as err:
        raise MOOError(f'filewrite({directory}, {filename}): {err}')


def fileappend(directory, filename, lines) -> int:
    """
    Inferno's ``fileappend()``: add lines to the end of a file.

    Creates the file, and any directory it needs, when absent -- the
    callers are logs, and a log that fails because nobody made its
    directory is worse than one that makes it.

    Args:
        directory: Directory, relative to the files root.
        filename: File within it.
        lines: Lines to add.

    Returns:
        int: 1 on success.  Callers test it (``if fileappend(...)``).
    """
    path = _resolve(directory, filename)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'a', encoding='utf-8') as fh:
            for line in (lines or []):
                fh.write(f'{line}\n')
        return 1
    except OSError as err:
        raise MOOError(f'fileappend({directory}, {filename}): {err}')


def filelist(directory) -> List[List[str]]:
    """
    Inferno's ``filelist()``: what is in a directory.

    Args:
        directory: Directory, relative to the files root.

    Returns:
        list: ``[files, directories]``.  Callers read them as ``[1]`` and
        ``[2]``, MOO's 1-based indexing, so the order matters.
    """
    path = _resolve(directory)
    try:
        entries = sorted(os.listdir(path))
    except (FileNotFoundError, NotADirectoryError):
        return [[], []]
    except OSError as err:
        raise MOOError(f'filelist({directory}): {err}')
    files, dirs = [], []
    for e in entries:
        (dirs if os.path.isdir(os.path.join(path, e)) else files).append(e)
    return [files, dirs]


def filedelete(directory, filename) -> int:
    """
    Inferno's ``filedelete()``: remove a file.

    Args:
        directory: Directory, relative to the files root.
        filename: File within it.

    Returns:
        int: 1 if it was removed, 0 if it was not there.
    """
    path = _resolve(directory, filename)
    try:
        os.remove(path)
        return 1
    except FileNotFoundError:
        return 0
    except OSError as err:
        raise MOOError(f'filedelete({directory}, {filename}): {err}')


def fileexists(directory, filename) -> int:
    """
    Inferno's ``fileexists()``.

    Args:
        directory: Directory, relative to the files root.
        filename: File within it.

    Returns:
        int: 1 or 0.
    """
    return 1 if os.path.exists(_resolve(directory, filename)) else 0


def filelength(directory, filename) -> int:
    """
    Inferno's ``filelength()``: how many lines a file has.

    Args:
        directory: Directory, relative to the files root.
        filename: File within it.

    Returns:
        int: The line count, 0 when the file is absent.
    """
    return len(fileread(directory, filename))


def filemkdir(directory, name) -> int:
    """
    Inferno's ``filemkdir()``: make a directory.

    Args:
        directory: Parent directory, relative to the files root.
        name: The directory to create inside it.

    Returns:
        int: 1 on success.
    """
    path = _resolve(directory, name)
    try:
        os.makedirs(path, exist_ok=True)
        return 1
    except OSError as err:
        raise MOOError(f'filemkdir({directory}, {name}): {err}')


def filermdir(directory, name) -> int:
    """
    Remove a directory and everything in it.

    Args:
        directory: Parent directory, relative to the files root.
        name: The directory to remove.

    Returns:
        int: 1 if removed, 0 if it was not there.
    """
    path = _resolve(directory, name)
    if not os.path.isdir(path):
        return 0
    try:
        shutil.rmtree(path)
        return 1
    except OSError as err:
        raise MOOError(f'filermdir({directory}, {name}): {err}')


def filerename(directory, old, new) -> int:
    """
    Rename a file within a directory.

    Args:
        directory: Directory, relative to the files root.
        old: Current name.
        new: New name.  Resolved inside the root like any other, so a
            rename cannot be used to write outside it.

    Returns:
        int: 1 if renamed, 0 if the original was not there.
    """
    src = _resolve(directory, old)
    dst = _resolve(directory, new)
    if not os.path.exists(src):
        return 0
    try:
        os.replace(src, dst)
        return 1
    except OSError as err:
        raise MOOError(f'filerename({directory}, {old}, {new}): {err}')
