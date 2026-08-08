#!/usr/bin/env python3
"""
Convert substitution tokens from ``%`` to ``&``.

Why not ``sed s/%/&/g``: most per-cent signs in a MegaMOO tree are not
tokens.  In the shipped verbs there are 20 modulo operators and 178
``"..." % value`` format expressions, and a blind rewrite breaks all of
them.  Worse, ``%s`` is *both* Python's format spec and esub's
subject-name token, so ``"Hello %s" % name`` cannot be told from
``msg("Hello %s")`` by looking at the string alone -- only by looking at
what the string is used for.

So this tool works two ways:

* **Plain text** (database values -- descriptions, messages): rewrite a
  ``%`` only when a real token follows it.
* **Python** (verb files): rewrite only inside string literals, and skip
  any literal that is the left operand of a ``%`` operator, because that
  one is Python formatting and its ``%s`` must stay.

``%%`` is left alone.  It is an escape, and it stays an escape for as long
as ``%`` remains in ``SUBST_SIGILS``.

Usage::

    python3 tools/migrate_sigil.py --verbs "moo verbs" --dry
    python3 tools/migrate_sigil.py --verbs "moo verbs" --db test.db
"""

import argparse
import ast
import io
import pathlib
import re
import sqlite3
import sys
import tokenize

#: What counts as a token after the sigil.  Ordered longest-first so a
#: pronoun is not read as a one-letter colour code.
#: Multi-letter tokens, longest first so `%OMODE` is not read as `%O`
#: followed by stray text.  Gathered by grepping every `replace('%...')`
#: in the engine and the verb tree rather than from memory -- the first
#: version of this regex knew only single letters, and would have
#: converted `%S` while leaving `%OMODE` in the same sentence.  That
#: half-migration works only while both sigils are still recognised,
#: which is exactly the state this tool exists to get out of.
_WORDS = ('OMODE', 'MODE', 'CEPO', 'CEPP', 'CEPR', 'CEPS',
          'COPO', 'COPP', 'COPR', 'COPS',
          'EPO', 'EPP', 'EPR', 'EPS', 'OPO', 'OPP', 'OPR', 'OPS',
          'CN', 'CT', 'dir')

TOKEN = re.compile(r"""
    (?<!%)%(                 # a % not preceded by another (so %% is safe)
        <[^>]{1,40}>         #   %<245>, %<bg#FF0000>
      | """ + '|'.join(_WORDS) + r"""
                             #   %MODE %OMODE %CEPS %dir ...
      | [pP][sSoOpPaArR]     #   %ps %po %pp %pa %pr
      | [a-zA-Z](?![a-zA-Z]) #   %n %r %s %d %i %u %N %T ...
      | \d+                  #   %0 %1 ... raw-string slots
    )
""", re.VERBOSE)


def convert_text(text: str) -> str:
    """
    Convert tokens in plain text.

    Args:
        text: A stored string -- a description, a message template.

    Returns:
        str: The same text with ``%``-tokens rewritten to ``&``.
    """
    if not isinstance(text, str) or '%' not in text:
        return text
    return TOKEN.sub(lambda m: '&' + m.group(1), text)


#: `$name` (system reference) and `#12` (object literal) are MegaMOO
#: spellings that Python's parser rejects.  Both are replaced with an
#: underscore *of the same length* before parsing, so every string
#: literal keeps the line and column it has in the real file -- the
#: positions are the whole point, and a length-changing preprocess would
#: silently shift them.  `#` is only replaced before a digit, so ordinary
#: comments survive.
_SYSREF = re.compile(r'\$(?=[A-Za-z_])')
_OBJREF = re.compile(r'#(?=\d)')


def _parseable(src: str) -> str:
    """Make verb source parse as Python without moving anything."""
    return _OBJREF.sub('_', _SYSREF.sub('_', src))


def _format_operand_positions(src: str):
    """
    Positions of string literals used as the left side of ``%``.

    These are Python format strings: their ``%s`` belongs to Python and
    must not be touched.  Everything else in the file is fair game.

    Args:
        src: Python source.

    Returns:
        set[int]: Source line numbers occupied by such literals.
    """
    try:
        tree = ast.parse(_parseable(src))
    except SyntaxError:
        return None
    skip = set()

    def mark(node):
        """
        Mark every source line the literal occupies.

        Lines, not (line, column).  Python folds implicitly-concatenated
        literals into a single Constant carrying only the *first* line's
        position, so marking that one position left the continuation
        lines unprotected -- and a two-line logging format string had its
        second line converted while the first was spared.
        """
        start = getattr(node, 'lineno', None)
        end = getattr(node, 'end_lineno', start)
        if start:
            skip.update(range(start, (end or start) + 1))

    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            mark(node.left)
            continue
        # Lazy logging: logger.warning('... %s ...', value).  The literal
        # is not the left operand of a `%`, so the check above cannot see
        # it, but logging applies %-formatting to it all the same -- and
        # converting its %s produced "not all arguments converted during
        # string formatting" at the first line that logged anything.
        if isinstance(node, ast.Call) and len(node.args) > 1:
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else (
                fn.id if isinstance(fn, ast.Name) else '')
            if name in ('debug', 'info', 'warning', 'warn', 'error',
                        'exception', 'critical', 'log'):
                mark(node.args[0])
    return skip


def convert_python(src: str):
    """
    Convert tokens inside a Python source file's string literals.

    Args:
        src: Verb source.

    Returns:
        tuple[str, int]: The rewritten source and how many literals
        changed.  Returns the input unchanged with a count of ``-1`` when
        the file does not parse, so the caller can report it rather than
        write something broken.
    """
    skip = _format_operand_positions(src)
    if skip is None:
        return src, -1

    out, changed = [], 0
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError):
        return src, -1

    # FSTRING_MIDDLE as well as STRING.  Python 3.12 split f-strings into
    # FSTRING_START / FSTRING_MIDDLE / FSTRING_END, so on any modern
    # interpreter an f-string is not a STRING token and a converter that
    # checks only for STRING silently skips every one of them.  That is
    # most display code written this decade -- 64 verbs in test.db still
    # carried `%<245>` after a run that reported success.
    literal = (tokenize.STRING, tokenize.FSTRING_MIDDLE)
    for tok in toks:
        if tok.type in literal and (tok.start[0] not in skip):
            new = convert_text(tok.string)
            if new != tok.string:
                changed += 1
                tok = tok._replace(string=new)
        out.append(tok)
    if not changed:
        return src, 0
    return tokenize.untokenize(out), changed


def migrate_verbs(root: pathlib.Path, dry: bool):
    """Rewrite every ``.py`` under *root*."""
    files = changed = broken = 0
    for path in sorted(root.rglob('*.py')):
        files += 1
        src = path.read_text(errors='replace')
        new, n = convert_python(src)
        if n == -1:
            broken += 1
            print(f'  !! {path} does not parse -- skipped')
            continue
        if n:
            changed += 1
            print(f'  {path.relative_to(root)}: {n} literal(s)')
            if not dry:
                path.write_text(new)
    print(f'\n  {files} files, {changed} changed, {broken} unparseable'
          f'{" (dry run -- nothing written)" if dry else ""}')
    return changed


def migrate_db(path: pathlib.Path, dry: bool):
    """
    Rewrite tokens in stored strings and verb code.

    Verb ``code`` goes through the Python converter; everything else is
    plain text.
    """
    con = sqlite3.connect(str(path))
    total = 0
    # `properties` is its own table, not a column on `objects`.  Guessing
    # the schema instead of reading it meant the 70 rows that actually
    # hold display text -- descriptions, message templates, everything a
    # player reads -- were never examined, and the run reported success.
    for table, cols in (('properties', ('value',)), ('verbs', ('code',))):
        try:
            names = [r[1] for r in con.execute(f'pragma table_info({table})')]
        except sqlite3.Error:
            continue
        if not names:
            continue
        key = 'objnum' if 'objnum' in names else names[0]
        for col in cols:
            if col not in names:
                continue
            # Single quotes.  SQLite reads a double-quoted token as an
            # *identifier* when it can, so the double-quoted pattern this
            # used to carry matched nothing at all and the migration
            # cheerfully reported zero rows to change.
            rows = con.execute(
                f"select rowid, {col} from {table} where instr({col}, '%') > 0"
            ).fetchall()
            for rowid, val in rows:
                if not isinstance(val, str):
                    continue
                new = (convert_python(val)[0] if col == 'code'
                       else convert_text(val))
                if new != val and new is not None:
                    total += 1
                    if not dry:
                        con.execute(f'update {table} set {col}=? where rowid=?',
                                    (new, rowid))
    if not dry:
        con.commit()
    con.close()
    print(f'  {path.name}: {total} value(s) '
          f'{"would change" if dry else "changed"}')
    return total


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    ap.add_argument('--verbs', help='verb tree to convert')
    ap.add_argument('--db', help='database to convert')
    ap.add_argument('--dry', action='store_true',
                    help='report without writing')
    args = ap.parse_args(argv)

    if not args.verbs and not args.db:
        ap.error('give --verbs, --db, or both')
    if args.verbs:
        migrate_verbs(pathlib.Path(args.verbs).expanduser(), args.dry)
    if args.db:
        migrate_db(pathlib.Path(args.db).expanduser(), args.dry)
    return 0


if __name__ == '__main__':
    sys.exit(main())
