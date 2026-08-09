"""
Verb metadata carried in the verb's own docstring.

A verb file records one name -- the filename -- and its code.  Everything
else that makes the verb what it is lives in the database: its other
names, the abbreviations it answers to, whether it is hidden, and its
permission string.  So a world rebuilt from its verb tree came back
subtly wrong, and silently: ``look`` stopped answering to ``l``, the two
dozen direction names collapsed to ``n``, and hidden internal hooks like
``_buy`` became commands a player could type.

Measured on the shipped starter world, a rebuild lost 20 alias sets, 56
abbreviation tables, one hidden flag and two permission strings.

The fix is the one the engine already uses for ``auth``: let the file
describe itself.  ``auth_level_required()`` reads the level out of the
verb's own guard, so a staff verb arrives from disk still being staff.
This module does the same for the rest, reading and writing four lines in
the docstring::

    Aliases: @create
    Abbrev:  @make=3, @create=3
    Hidden:  yes
    Perms:   rxd

Only ``Aliases`` names the *other* names; the primary is the filename and
is never repeated.  Lines are omitted when they carry nothing --  no
aliases, no abbreviations, not hidden, ordinary ``rx`` permissions -- so
the overwhelming majority of verb files gain nothing at all.

The spelling matches ``@adverb``, which has always taken
``<name[(min)][,...]> [with <perms>]``; this is the same information at
rest that ``@adverb`` takes at the command line.

Only the leading docstring is searched.  A verb whose body happens to
contain a line beginning "Hidden:" -- a message, a help table -- must not
be read as declaring itself hidden.
"""
import re
from typing import Dict, List, Optional, Tuple

#: The four fields, anchored at line start inside the docstring.
_ALIASES = re.compile(r'^[ \t]*Aliases:[ \t]*(.*)$', re.M | re.I)
_ABBREV = re.compile(r'^[ \t]*Abbrev:[ \t]*(.*)$', re.M | re.I)
_HIDDEN = re.compile(r'^[ \t]*Hidden:[ \t]*(\S+)', re.M | re.I)
_PERMS = re.compile(r'^[ \t]*Perms:[ \t]*(\S+)', re.M | re.I)

#: ``@create`` or ``@create(3)`` -- @adverb's spelling, accepted here too
#: so a name copied from an @adverb command line parses.
_NAME = re.compile(r'^([^\s(]+)(?:\((\d+)\))?$')

_TRUE = {'yes', 'true', '1', 'on'}


def docstring_region(code: str) -> Optional[Tuple[int, int]]:
    """
    Span of the leading docstring's *contents*, or None if there is none.

    Returns ``(start, end)`` indices into *code* bounded by the quotes, so
    the caller can read or rewrite the inside without disturbing them.
    """
    text = code.lstrip()
    if not text[:3] in ('"""', "'''"):
        return None
    quote = text[:3]
    offset = len(code) - len(text)
    start = offset + 3
    end = code.find(quote, start)
    if end == -1:
        return None
    return start, end


def _docstring(code: str) -> str:
    span = docstring_region(code or '')
    return (code or '')[span[0]:span[1]] if span else ''


def _split_names(value: str) -> List[Tuple[str, Optional[int]]]:
    """``"@create, @build(2)"`` -> ``[('@create', None), ('@build', 2)]``."""
    out = []
    for chunk in value.replace(';', ',').split(','):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = _NAME.match(chunk)
        if not m:
            continue
        out.append((m.group(1), int(m.group(2)) if m.group(2) else None))
    return out


def parse_verb_meta(code: str, primary: str) -> Dict:
    """
    Read a verb file's declared metadata.

    Args:
        code: the file's full source.
        primary: the name the file itself carries, which is always first
            in the resulting name list and never declared in ``Aliases``.

    Returns:
        ``{'names', 'min_lengths', 'hidden', 'perms'}``.  Fields the file
        does not declare come back as their defaults, so a verb file with
        no metadata at all describes an ordinary, visible, ``rx`` verb
        with no aliases -- which is what the great majority of them are.
    """
    doc = _docstring(code)
    names: List[str] = [primary]
    min_lengths: Dict[str, int] = {}

    m = _ALIASES.search(doc)
    if m:
        for name, minimum in _split_names(m.group(1)):
            if name not in names:
                names.append(name)
            if minimum is not None:
                min_lengths[name] = minimum

    m = _ABBREV.search(doc)
    if m:
        # `@make=3, @create=3` -- and `@make(3)` for symmetry with Aliases.
        for chunk in m.group(1).replace(';', ',').split(','):
            chunk = chunk.strip()
            if not chunk:
                continue
            if '=' in chunk:
                name, _, raw = chunk.partition('=')
                name, raw = name.strip(), raw.strip()
                if raw.isdigit():
                    min_lengths[name] = int(raw)
            else:
                for name, minimum in _split_names(chunk):
                    if minimum is not None:
                        min_lengths[name] = minimum

    m = _HIDDEN.search(doc)
    hidden = bool(m and m.group(1).strip().lower() in _TRUE)

    m = _PERMS.search(doc)
    perms = m.group(1).strip() if m else 'rx'

    # An abbreviation for a name the verb does not have is noise, and
    # would otherwise travel from file to file by copy-paste forever.
    min_lengths = {k: v for k, v in min_lengths.items() if k in names}

    return {'names': names, 'min_lengths': min_lengths,
            'hidden': hidden, 'perms': perms}


def render_verb_meta(code: str, names, min_lengths=None, hidden=False,
                     perms='rx') -> str:
    """
    Write metadata into *code*'s docstring, replacing any already there.

    Lines carrying nothing are omitted, and removed if present -- so
    un-hiding a verb takes the ``Hidden:`` line out rather than leaving a
    ``Hidden: no`` behind to be misread later as deliberate.

    A file with no docstring is returned unchanged.  Inventing one would
    mean guessing at a summary line, and a verb with metadata but no
    documentation is a verb worth opening by hand.
    """
    span = docstring_region(code or '')
    if span is None:
        return code
    start, end = span
    doc = code[start:end]

    names = list(names or [])
    aliases = names[1:]
    min_lengths = dict(min_lengths or {})

    lines = []
    if aliases:
        lines.append('Aliases: ' + ', '.join(aliases))
    if min_lengths:
        ordered = [n for n in names if n in min_lengths]
        lines.append('Abbrev:  ' + ', '.join(
            '%s=%d' % (n, min_lengths[n]) for n in ordered))
    if hidden:
        lines.append('Hidden:  yes')
    if (perms or 'rx') != 'rx':
        lines.append('Perms:   %s' % perms)

    # Strip whatever is there now, including the blank line that followed
    # a block, so repeated renders do not accumulate spacing.
    kept = []
    for line in doc.split('\n'):
        if (_ALIASES.match(line) or _ABBREV.match(line)
                or _HIDDEN.match(line) or _PERMS.match(line)):
            continue
        kept.append(line)
    doc = '\n'.join(kept)

    if lines:
        block = '\n'.join(lines)
        auth_at = re.search(r'^[ \t]*Auth:', doc, re.M)
        if auth_at:
            # Directly above Auth, so the whole gm/visibility story reads
            # as one paragraph.
            doc = doc[:auth_at.start()] + block + '\n' + doc[auth_at.start():]
        else:
            doc = doc.rstrip('\n') + '\n\n' + block + '\n'

    return code[:start] + doc + code[end:]
