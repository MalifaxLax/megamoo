"""
Translate MOO source into Python, and say so when it cannot.

This is a porting *assistant*, not a compiler.  It reads MOO with a real
tokeniser and parser -- not patterns -- because the failure mode of guessing
at a language is code that runs, reads correctly, and is quietly wrong.

The single largest hazard is indexing.  MOO lists and strings are 1-based
and its ranges are inclusive, so ``x[1]`` is ``x[0]`` here and ``x[2..5]``
is ``x[1:5]``.  Get one wrong and nothing crashes; a list is simply off by
one, months later, in the middle of a game rule.  Every shifted index is
translated explicitly, and anything the translator is unsure of is marked
in the output rather than quietly emitted.

What it will not do
-------------------

``read()`` is left as a marked comment rather than approximated: it blocks
for player input, and there is no faithful one-line equivalent.  A
plausible-looking wrong translation is worse than an obvious hole.

Where a construct has no Python *syntax* but does have honest semantics, it
goes through a helper instead of being refused.  ``raise()`` inside an
expression becomes ``moo_raise()``, assignment inside an expression becomes
``moo_setprop``/``moo_setitem``, and ``fork`` becomes a deferred code string
handed to the scheduler.  A function call is an expression, so the idiom
survives; refusing these only moved the work to a human who would have
written the same thing.

Everything it emits that a human should check carries a ``# PORT:`` line, so
the residue is greppable.  A verb with no ``# PORT:`` markers is one the
translator believes it handled completely -- which is a claim about the
mechanical parts only, never about whether the logic is right.
"""

import ast
import keyword
import re
from typing import List, Optional, Tuple

__all__ = ['port', 'PortResult', 'MooSyntaxError', 'undefined_names']

MARK = '# PORT:'

#: System references with a real equivalent.  Anything else becomes a
#: marked lookup rather than a guess at what the object was called.
SYSREFS = {
    'string_utils': 'su',
    'object_utils': 'ou',
    'list_utils': 'lu',
    'command_utils': 'cu',
    'code_utils': 'cdu',
    'perm_utils': 'pu',
    'player': 'pobj',
}

#: System references that name a *value*, not an object.  MOO spells "no
#: object" several ways: $nothing and $no_one are #-1 and mean None here.
#: The other two are what MOO's matcher returns to tell "no such thing"
#: apart from "which one did you mean"; this engine returns None for both,
#: so they map to sentinels nothing ever produces rather than to None --
#: see moo_libs for why conflating them would be worse than leaving them.
SYSCONSTANTS = {
    'nothing': 'None',
    'no_one': 'None',
    'failed_match': 'FAILED_MATCH',
    'ambiguous_match': 'AMBIGUOUS_MATCH',
}

#: Verb-namespace variables that exist here under another name.  Every
#: other MOO name -- this, caller, verb, argstr, args, dobj, dobjstr, iobj,
#: iobjstr -- is spelled the same and needs no mapping.
VARIABLES = {
    'player': 'pobj',
    'prepstr': 'prep',
}

#: Mapped sysrefs that are Python objects rather than MOO objects.  A
#: ``:verb()`` call on one of these is a method call, not a verb call.
_PY_RECEIVERS = {'su', 'ou', 'lu', 'cu', 'cdu', 'pu'}

#: MOO builtins that map straight onto Python.
BUILTINS = {
    'length': 'len', 'abs': 'abs', 'min': 'min', 'max': 'max',
    'random': 'random', 'floor': 'int', 'sqrt': 'sqrt',
    'tostr': None, 'toint': 'int', 'tofloat': 'float', 'toobj': None,
    'typeof': None, 'valid': None,
}

#: MOO's type constants, which only ever appear in `typeof(x) == LIST`.
#: Both spellings, because the two common cores disagree.  JHCore writes
#: LIST and STR; LambdaCore writes TYPE_LIST and TYPE_STR, and neither uses
#: the other's form at all -- 350 vs 0 and 253 vs 0 across the two.  A
#: translator that knew only one would leave the other as an undefined name.
TYPE_TESTS = {
    'LIST': 'list', 'STR': 'str', 'NUM': 'int', 'INT': 'int',
    'FLOAT': 'float', 'OBJ': 'MOOObject', 'ERR': 'MOOError',
    'TYPE_LIST': 'list', 'TYPE_STR': 'str', 'TYPE_NUM': 'int',
    'TYPE_INT': 'int', 'TYPE_FLOAT': 'float', 'TYPE_OBJ': 'MOOObject',
    'TYPE_ERR': 'MOOError',
}

#: Constructs deliberately not translated.
REFUSED = {
    'read': 'read() blocks for player input; use an interactive session',
}


def _has_bare_colon(text: str) -> bool:
    """Whether *text* is a slice rather than a single index."""
    depth = 0
    for ch in text:
        if ch in '([{':
            depth += 1
        elif ch in ')]}':
            depth -= 1
        elif ch == ':' and depth == 0:
            return True
    return False


def _safe_name(name: str) -> str:
    """
    Rename a MOO variable that Python will not let us spell.

    ``from``, ``class``, ``as``, ``is``, ``in``, ``lambda``, ``global``
    and ``None`` are all perfectly ordinary variable names in MOO, and
    JHCore uses several of them -- ``from`` alone appears in thirteen
    verbs, mostly the mail system.  Left alone they produce a syntax
    error, which is at least loud, but the verb does not run at all.

    A trailing underscore is the fix, and it has to happen here, at the
    single point where a name is translated, so that reads and writes are
    renamed identically.  Renaming in one place and not the other would
    turn a syntax error into a verb that runs and quietly uses the wrong
    variable.

    Args:
        name: The translated name.

    Returns:
        The name, with ``_`` appended if Python has claimed it.
    """
    if keyword.iskeyword(name) or name in ('None', 'True', 'False'):
        return name + '_'
    return name


class MooSyntaxError(Exception):
    """The source could not be parsed as MOO."""


class PortResult:
    """What came back from a translation."""

    def __init__(self, code: str, notes: List[str], marks: int):
        self.code = code
        self.notes = notes          # human-readable, for the editor to show
        self.marks = marks          # how many # PORT: lines are in the code

    @property
    def clean(self) -> bool:
        """True when nothing needed marking."""
        return self.marks == 0


# ---------------------------------------------------------------------------
# Tokeniser
# ---------------------------------------------------------------------------

TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<string>"[^"\\]*(?:\\.[^"\\]*)*")
  | (?P<objnum>\#\s*-?\d+)
  | (?P<sysref>\$[A-Za-z_]\w*)
  | (?P<dollar>\$)
  | (?P<number>\d+\.\d+|\d+)
  | (?P<name>[A-Za-z_]\w*)
  | (?P<range>\.\.)
  | (?P<op><=|>=|==|!=|&&|\|\||=>|[-+*/%<>=!?|:.,;()\[\]{}@`'])
""", re.X)


def tokenise(src: str) -> List[Tuple[str, str, int]]:
    """Return ``(kind, text, line)`` triples."""
    out, pos, line = [], 0, 1
    while pos < len(src):
        m = TOKEN_RE.match(src, pos)
        if not m:
            raise MooSyntaxError(f"line {line}: cannot read {src[pos:pos+20]!r}")
        kind = m.lastgroup
        text = m.group()
        line += text.count('\n')
        if kind != 'ws':
            out.append((kind, text, line))
        pos = m.end()
    out.append(('eof', '', line))
    return out


# ---------------------------------------------------------------------------
# Parser + emitter
#
# Kept as one pass: MOO's grammar is small, the output is Python source
# rather than another tree, and a separate AST would add a layer without
# adding a decision.
# ---------------------------------------------------------------------------

class Porter:
    def __init__(self, src: str):
        self.toks = tokenise(src)
        self.i = 0
        self.notes: List[str] = []
        self.marks = 0
        #: Modules the translation needs that a verb namespace
        #: does not already provide.  Emitted as imports rather
        #: than asked for in a note.
        self.needs_import = set()
        self.depth = 0
        self.receiver: List[str] = []

    # -- token helpers ----------------------------------------------------
    def peek(self, ahead=0):
        j = min(self.i + ahead, len(self.toks) - 1)
        return self.toks[j]

    def at(self, text) -> bool:
        return self.peek()[1] == text

    def at_name(self, word) -> bool:
        k, t, _ = self.peek()
        return k == 'name' and t == word

    def next(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect(self, text):
        k, t, ln = self.next()
        if t != text:
            raise MooSyntaxError(f"line {ln}: expected {text!r}, got {t!r}")
        return t

    def note(self, msg):
        if msg not in self.notes:
            self.notes.append(msg)

    def mark(self, msg) -> str:
        """Mark something for a human.  Safe only at end of statement."""
        self.marks += 1
        self.note(msg)
        return f"{MARK} {msg}"

    def mark_expr(self, msg: str, original: str) -> str:
        """
        Mark something *inside* an expression.

        A `#` comment cannot go here -- it would comment out the rest of
        the line and the result would not compile.  So the placeholder is
        a bare None and the original is carried in the notes, which the
        header reproduces.
        """
        self.marks += 1
        self.note(f'{msg}  --  was: {original}')
        return 'None'


    def _paren(self, fn):
        """Parse inside parentheses, so assignment-as-expression is legal."""
        self.depth += 1
        try:
            return fn()
        finally:
            self.depth -= 1

    # -- statements -------------------------------------------------------
    def block(self, indent: int, stop: Tuple[str, ...]) -> List[str]:
        out = []
        while True:
            k, t, ln = self.peek()
            if k == 'eof' or (k == 'name' and t in stop):
                # A body that translated to nothing but comments is not an
                # indented block as far as Python is concerned, so it needs
                # a statement to stand on.
                if not out or all(l.strip().startswith('#') for l in out):
                    out.append('    ' * indent + 'pass')
                return out
            out.extend(self.statement(indent))

    def statement(self, indent: int) -> List[str]:
        pad = '    ' * indent
        k, t, ln = self.peek()

        # A bare string statement is MOO's comment.  Detected here rather
        # than in the tokeniser, which cannot tell it apart from a string
        # on the right of an assignment -- `x = "";` is not a comment.
        if k == 'string' and self.peek(1)[1] == ';':
            self.next()
            self.next()
            return [f'{pad}# {t[1:-1]}']

        if k == 'name':
            if t in REFUSED:
                return self._refuse(indent, t)
            if t == 'if':
                return self.if_stmt(indent)
            if t == 'for':
                return self.for_stmt(indent)
            if t == 'while':
                return self.while_stmt(indent)
            if t == 'try':
                return self.try_stmt(indent)
            if t == 'fork':
                return self.fork_stmt(indent)
            if t == 'return':
                self.next()
                if self.at(';'):
                    self.next()
                    return [f'{pad}return']
                e = self.expr()
                # `return x = y` assigns and then returns.  Python cannot
                # do both in one statement unless the target is a plain
                # name, so it becomes two lines.
                if self.at('=') and self.peek(1)[1] != '=':
                    self.next()
                    rhs = self.expr()
                    self.eat_semi()
                    return [pad + _assign(e, rhs), f'{pad}return {e}']
                self.eat_semi()
                return [f'{pad}return {e}']
            if t == 'raise' and self.peek(1)[1] == '(':
                # The whole statement is a raise, which Python can express.
                self.next()
                self.expect('(')
                what = self._paren(lambda: ', '.join(self.arglist(')')))
                self.eat_semi()
                return [f'{pad}raise {what}']
            if t in ('break', 'continue'):
                self.next()
                self.eat_semi()
                return [f'{pad}{t}']

        # scatter assignment:  {a, ?b = d, @rest} = expr
        if self.at('{'):
            saved = self.i
            scatter = self.try_scatter()
            if scatter is not None:
                return [pad + line for line in scatter]
            self.i = saved

        # assignment, possibly chained:  a = b = c = expr
        targets = [self.expr()]
        while self.at('=') and self.peek(1)[1] != '=':
            self.next()
            targets.append(self.expr())
        self.eat_semi()
        if len(targets) == 1:
            return [f'{pad}{targets[0]}']
        if len(targets) == 2:
            return [pad + _assign(targets[0], targets[1])]
        # Python chains natively and right-to-left, same as MOO.  Only
        # plain names can chain, so a computed target falls back to
        # separate statements.
        if any(t.startswith('getattr(') for t in targets[:-1]):
            value = targets[-1]
            return [pad + _assign(t, value) for t in targets[:-1]]
        return [pad + ' = '.join(targets)]

    def try_scatter(self) -> Optional[List[str]]:
        """
        Parse `{a, ?b = d, @rest} = expr`, or give up and return None.

        MOO's scatter has three item kinds: required, optional (with an
        optional default), and rest.  Python unpacking covers required and
        rest exactly; it has nothing for optionals, because it raises when
        the right-hand side is too short rather than leaving a name unbound.
        Those are marked rather than approximated -- silently binding a
        default that MOO would have left unset is the sort of difference
        that surfaces much later.
        """
        self.expect('{')
        names, optional, rest = [], [], None
        while not self.at('}'):
            if self.at('@'):
                self.next()
                rest = self.next()[1]
            elif self.at('?'):
                self.next()
                nm = self.next()[1]
                default = None
                if self.at('='):
                    self.next()
                    default = self._paren(self.expr)
                optional.append((nm, default))
                names.append(nm)
            else:
                k, t, _ = self.peek()
                if k != 'name':
                    return None
                self.next()
                names.append(t)
            if self.at(','):
                self.next()
                continue
            break
        if not self.at('}'):
            return None
        self.next()
        if not self.at('='):
            return None            # a list literal, not a scatter target
        self.next()
        value = self.expr()
        self.eat_semi()

        required = [n for n in names if n not in {o[0] for o in optional}]
        target = ', '.join(required + ([f'*{rest}'] if rest else []))
        out = []
        if optional:
            for nm, default in optional:
                out.append(self.mark(
                    f'optional scatter target {nm!r}'
                    + (f' defaulting to {default}' if default else '')
                    + ': Python unpacking has no equivalent, set it by hand'))
        if not target:
            return out + [f'# {value}']
        return out + [f'{target} = {value}']

    def _refuse(self, indent, word) -> List[str]:
        """Consume a construct we will not translate, and mark it."""
        pad = '    ' * indent
        depth = 0
        raw = []
        end = {'try': 'endtry'}.get(word)
        while True:
            k, t, ln = self.peek()
            if k == 'eof':
                break
            if end and k == 'name' and t == word:
                depth += 1
            raw.append(t)
            self.next()
            if end:
                if k == 'name' and t == end:
                    depth -= 1
                    if depth <= 0:
                        break
            elif t == ';':
                break
        why = REFUSED.get(word, f'{word} has no faithful equivalent')
        head = self.mark(f'{word}: {why}')
        body = ' '.join(raw)
        return [f'{pad}{head}'] + [f'{pad}#   {line}'
                                   for line in _wrap(body, 66)]

    def eat_semi(self):
        if self.at(';'):
            self.next()

    def if_stmt(self, indent) -> List[str]:
        pad = '    ' * indent
        self.expect('if')
        self.expect('(')
        cond = self._paren(self.expr)
        self.expect(')')
        out = [f'{pad}if {cond}:']
        out += self.block(indent + 1, ('elseif', 'else', 'endif'))
        while self.at_name('elseif'):
            self.next()
            self.expect('(')
            c = self._paren(self.expr)
            self.expect(')')
            out.append(f'{pad}elif {c}:')
            out += self.block(indent + 1, ('elseif', 'else', 'endif'))
        if self.at_name('else'):
            self.next()
            out.append(f'{pad}else:')
            out += self.block(indent + 1, ('endif',))
        if self.at_name('endif'):
            self.next()
            self.eat_semi()
        return out

    def for_stmt(self, indent) -> List[str]:
        pad = '    ' * indent
        self.expect('for')
        var = self.next()[1]
        self.expect('in')
        # Two forms, and only one of them is parenthesised:
        #   for x in (a_list)      iterate a list
        #   for i in [1..n]        numeric range, inclusive at both ends
        if self.at('['):
            self.next()
            lo = self._paren(self.expr)
            self.expect('..')
            hi = self._paren(self.expr)
            self.expect(']')
            head = f'{pad}for {var} in range({lo}, ({hi}) + 1):'
        else:
            self.expect('(')
            seq = self._paren(self.expr)
            self.expect(')')
            head = f'{pad}for {var} in {seq}:'
        out = [head] + self.block(indent + 1, ('endfor',))
        if self.at_name('endfor'):
            self.next()
            self.eat_semi()
        return out

    def try_stmt(self, indent) -> List[str]:
        """
        `try ... except (codes) ... endtry` -- a statement in both languages.

        This one does map directly; it was previously refused out of
        caution.  MOO names the codes in parentheses and may bind the error
        to a variable; Python spells that `except MOOError as e`, with the
        code check inside since MOO's codes are values rather than classes.
        """
        pad = '    ' * indent
        self.expect('try')
        out = [f'{pad}try:'] + self.block(indent + 1, ('except', 'finally',
                                                       'endtry'))
        while self.at_name('except'):
            self.next()
            var = None
            if self.peek()[0] == 'name' and self.peek()[1] != 'ANY':
                var = self.next()[1]
            codes = []
            if self.at('('):
                self.next()
                while not self.at(')'):
                    k, t, _ = self.peek()
                    if k == 'name':
                        codes.append(self.next()[1])
                    else:
                        self.next()
                    if self.at(','):
                        self.next()
                if self.at(')'):
                    self.next()
            name = var or '_err'
            out.append(f'{pad}except MOOError as {name}:')
            body = self.block(indent + 1, ('except', 'finally', 'endtry'))
            if codes and 'ANY' not in codes:
                names = ', '.join(f"'{c}'" for c in codes)
                out.append(f'{pad}    if {name}.code not in ({names},):')
                out.append(f'{pad}        raise')
            out += body
        if self.at_name('finally'):
            self.next()
            out.append(f'{pad}finally:')
            out += self.block(indent + 1, ('endtry',))
        if self.at_name('endtry'):
            self.next()
            self.eat_semi()
        return out

    def fork_stmt(self, indent) -> List[str]:
        """
        ``fork (n) ... endfork`` -- run a block later, in its own task.

        The engine's fork() takes the deferred work as a *code string*
        rather than a callable, because a scheduled task is resumed on a
        fresh thread out of a queue and there is no live frame to
        re-enter.  So the body is translated like any other block, bound
        to a name above the call, and handed over with a snapshot of the
        namespace.

        The snapshot is the part with a real consequence, and it matches
        MOO: a forked task sees the values its parent held at the moment
        of the fork, not whatever they became afterwards.  A verb that
        forks inside a loop and expects the loop variable to have moved
        on is disappointed here exactly as it would be there.

        The body is bound to a variable rather than written inline
        because it is a multi-line string in the middle of a call
        argument, and putting it there would wreck the indentation of
        everything around it.
        """
        pad = '    ' * indent
        self.expect('fork')
        # `fork name (n)` binds the new task id.  Unlike while's loop
        # label this is worth keeping -- it is a real value, and
        # kill_task() is called with it later.
        target = None
        if self.peek()[0] == 'name' and self.peek(1)[1] == '(':
            target = self.next()[1]
        self.expect('(')
        secs = self._paren(self.expr)
        self.expect(')')
        body = self.block(0, ('endfork',))
        self.expect('endfork')

        self._forks = getattr(self, '_forks', 0) + 1
        name = f'_forked_{self._forks}'
        text = '\n'.join(body)
        lhs = f'{target} = ' if target else ''

        # Triple quotes keep the deferred code readable in the output, but
        # only when the body cannot end them early.  repr() is always
        # correct, so it is the fallback rather than the default.
        if "'''" in text or text.endswith("'") or '\\' in text:
            return [f'{pad}{name} = {text!r}',
                    f'{pad}{lhs}fork({secs}, {name}, dict(globals()))']
        # Both the body and the closing quote sit at column 0 even inside
        # an indented block.  Indentation inside a string literal is part
        # of the string, and the deferred code is compiled on its own, so
        # a padded body would arrive pre-indented and fail to parse.
        return ([f"{pad}{name} = '''"] +
                text.splitlines() +
                ["'''",
                 f'{pad}{lhs}fork({secs}, {name}, dict(globals()))'])

    def while_stmt(self, indent) -> List[str]:
        pad = '    ' * indent
        self.expect('while')
        # MOO 1.8 allows a loop label: `while searching (queue)`.  It only
        # matters to break/continue targeting it, which Python cannot do
        # anyway, so it is consumed and noted rather than kept.
        if self.peek()[0] == 'name' and self.peek(1)[1] == '(':
            label = self.next()[1]
            self.note(f'loop label {label!r} dropped; Python cannot break '
                      f'to a label, so check any break/continue inside')
            self.marks += 1
        self.expect('(')
        cond = self._paren(self.expr)
        self.expect(')')
        out = [f'{pad}while {cond}:'] + self.block(indent + 1, ('endwhile',))
        if self.at_name('endwhile'):
            self.next()
            self.eat_semi()
        return out

    # -- expressions ------------------------------------------------------
    #: Precedence, loosest first, following mooR's binding-power table.
    #: `||` and `&&` share a level there -- both (3, 4), left-associative --
    #: where Python binds `and` tighter than `or`.  They are kept together
    #: here and the result parenthesised, so `a || b && c` stays
    #: `(a or b) and c` instead of being reread as `a or (b and c)`.
    BIN = [
        (('||', '&&'), None),
        (('==', '!=', '<', '>', '<=', '>=', 'in'), None),
        (('+', '-'), None), (('*', '/', '%'), None),
    ]

    def expr(self) -> str:
        """A full expression: conditional, then assignment."""
        left = self.binary(0)

        # MOO's conditional, at any depth:  cond ? a | b
        if self.at('?'):
            self.next()
            a = self._paren(self.expr)
            self.expect('|')
            b = self._paren(self.expr)
            left = f'({a} if {left} else {b})'

        # MOO assignment is an expression, so `if (x = foo())` is legal and
        # common.  Python's walrus is the exact equivalent.  Only inside
        # parentheses: at statement level the caller handles `=` itself.
        if self.depth and self.at('=') and self.peek(1)[1] != '=':
            self.next()
            rhs = self.expr()
            if left.isidentifier():
                left = f'({left} := {rhs})'
            else:
                # Python's walrus binds plain names only, so a property or
                # element target has no inline form.  A call is still an
                # expression, though, so the write goes through a helper
                # instead of being marked and left for a human.
                #
                # The two helpers do not return the same thing, and that
                # is MOO's doing rather than a wrinkle here: `o.p = v`
                # evaluates to v, but `l[i] = v` evaluates to the whole
                # list, because MOO lists are values and the assignment
                # produces the new one.
                target = self._split_target(left)
                if target is None:
                    left = self.mark_expr(
                        'assignment inside an expression to something with '
                        'no inline form; lift it to its own statement',
                        f'{left} = {rhs}')
                elif target[0] == 'prop':
                    left = f'moo_setprop({target[1]}, {target[2]!r}, {rhs})'
                else:
                    left = f'moo_setitem({target[1]}, {target[2]}, {rhs})'
        return left

    @staticmethod
    def _split_target(text: str):
        """
        Take apart an already-translated assignment target.

        Args:
            text: Translated Python for the left side, e.g. ``this.name``
                or ``lst[i - 1]``.

        Returns:
            ``('prop', obj, name)``, ``('item', seq, index)``, or None if
            it is not a shape that can be written through a helper.

        The bracket scan counts depth rather than searching for the first
        ``[``, because the container is itself an expression and may carry
        brackets of its own -- ``x[1][2]`` must split at the last pair.
        """
        if text.endswith(']'):
            depth = 0
            for i in range(len(text) - 1, -1, -1):
                if text[i] == ']':
                    depth += 1
                elif text[i] == '[':
                    depth -= 1
                    if depth == 0:
                        seq, index = text[:i], text[i + 1:-1]
                        if not seq or not index:
                            return None
                        # A range target -- MOO's x[i..j] = v -- arrives as
                        # a Python slice, and `a:b` is not an expression,
                        # so it cannot be passed to a helper.  Refuse it
                        # rather than emit something that will not compile.
                        if _has_bare_colon(index):
                            return None
                        return ('item', seq, index)
            return None
        head, dot, name = text.rpartition('.')
        if dot and name.isidentifier() and head:
            return ('prop', head, name)
        return None

    def binary(self, level: int) -> str:
        if level >= len(self.BIN):
            return self.unary()
        ops, word = self.BIN[level]
        left = self.binary(level + 1)
        while True:
            k, t, _ = self.peek()
            if k == 'name' and t == 'in' and 'in' in ops:
                self.next()
                right = self.binary(level + 1)
                # MOO's `in` yields a 1-based index, or 0 when absent --
                # not a boolean.  Translating it to Python's `in` would be
                # right for a truth test and wrong everywhere else.
                left = (f'(({right}).index({left}) + 1 '
                        f'if ({left}) in ({right}) else 0)')
                continue
            if k == 'op' and t in ops:
                op = self.next()[1]
                right = self.binary(level + 1)
                if op in ('||', '&&'):
                    # Parenthesised because MOO and Python disagree about
                    # how these two bind relative to each other.
                    py = 'or' if op == '||' else 'and'
                    left = f'({left} {py} {right})'
                    continue
                # `typeof(x) == LIST` is how MOO asks about a type, and it
                # is the only place its type constants appear.  Turn the
                # whole comparison into an isinstance(), rather than emit
                # a _typeof() and a bare LIST that exist nowhere.
                pair = TYPE_TESTS.get(right) or TYPE_TESTS.get(left)
                fn_side = left if left.startswith('typeof(') else right
                if pair and fn_side.startswith('typeof(') and op in ('==', '!='):
                    inner = fn_side[len('typeof('):-1]
                    test = f'isinstance({inner}, {pair})'
                    left = test if op == '==' else f'not {test}'
                    continue
                left = f'{left} {word or op} {right}'
                continue
            return left

    def unary(self) -> str:
        if self.at('!'):
            self.next()
            return f'not {self.unary()}'
        if self.at('-'):
            self.next()
            return f'-{self.unary()}'
        if self.at('`'):
            return self.backtick()
        return self.postfix(self.primary())

    def backtick(self) -> str:
        """
        ```expr ! codes => fallback'`` -- MOO's expression-level catch.

        mooR models this as a TryCatch *expression* and compiles it to a
        catch label in its VM.  Python has no expression-level try, but
        deferring both halves into callables gives the same semantics and
        keeps it an expression, so it still nests anywhere MOO's does.
        """
        self.expect('`')
        attempt = self._paren(self.expr)

        codes = []
        if self.at('!'):
            self.next()
            while True:
                k, t, ln = self.peek()
                if k != 'name':
                    break
                codes.append(self.next()[1])
                if self.at(','):
                    self.next()
                    continue
                break

        fallback = None
        if self.at('=>'):
            self.next()
            fallback = self._paren(self.expr)

        self.expect("'")

        code_tuple = ('(' + ', '.join(f"'{c}'" for c in codes) +
                      (',)' if len(codes) == 1 else ')')) if codes else "('ANY',)"
        # E_PROPNF used to be marked here: a missing property returns the
        # falsy sentinel rather than raising, so the fallback would not
        # have fired and the sentinel would have been the value.  catch()
        # now recognises the sentinel and applies the fallback, which is
        # the right place for the fix -- one function rather than a note on
        # every backtick in the corpus.

        if fallback is None:
            # Without `=>` the value is the error itself, which is what
            # catch() returns when given no fallback.
            return f'catch(lambda: {attempt}, {code_tuple})'
        return f'catch(lambda: {attempt}, {code_tuple}, lambda: {fallback})'

    def primary(self) -> str:
        k, t, ln = self.next()
        if k == 'number':
            return t
        if k == 'string':
            return t
        if k == 'objnum':
            return '#' + t[1:].strip()
        if k == 'sysref':
            name = t[1:]
            if name in SYSREFS:
                return SYSREFS[name]
            if name in SYSCONSTANTS:
                return SYSCONSTANTS[name]
            return self.mark_expr(
                f'${name}: no equivalent object; point this at the right one',
                f'${name}')
        if t == '(':
            e = self._paren(self.expr)
            self.expect(')')
            return f'({e})'
        if t == '{':
            items = self.arglist('}')
            return '[' + ', '.join(items) + ']'
        if k == 'dollar':
            if not self.receiver:
                raise MooSyntaxError(f'line {ln}: $ outside an index')
            return f'len({self.receiver[-1]})'
        if k == 'name':
            # Only *variables* get the keyword rename.  A name followed by
            # `(` is a call, and the call handler dispatches on MOO's own
            # spelling -- renaming `raise` to `raise_` here would hide it
            # from the branch that knows what raise() means.
            if self.at('('):
                return VARIABLES.get(t, t)
            return _safe_name(VARIABLES.get(t, t))
        raise MooSyntaxError(f'line {ln}: unexpected {t!r}')

    def postfix(self, val: str) -> str:
        while True:
            if self.at('.'):
                self.next()
                if self.at('('):
                    # obj.(expr) -- the property name is computed.
                    self.next()
                    name = self._paren(self.expr)
                    self.expect(')')
                    val = f'getattr({val}, {name})'
                    continue
                k, t, ln = self.next()
                if k == 'string':          # obj."name"
                    val = f'getattr({val}, {t})'
                    continue
                val = f'{val}.{t}'
            elif self.at(':'):
                self.next()
                # obj:(expr)(args) -- the verb name is computed.
                if self.at('('):
                    self.next()
                    vname = self._paren(self.expr)
                    self.expect(')')
                    self.expect('(')
                    args = self.arglist(')')
                    inner = ''.join(f', {a}' for a in args)
                    val = f'call_verb({val}, {vname}{inner})'
                    continue
                name = self.next()[1]
                self.expect('(')
                args = self.arglist(')')
                if name == 'tell':
                    val = f'tell({val}' + (', ' + ', '.join(args) if args else '') + ')'
                elif name == 'notify':
                    # $player:notify(text) is MOO's standard "send this to
                    # that player" verb, wrapping the notify() builtin.
                    # There is no notify *verb* here -- msg is the one --
                    # so call_verb(x, 'notify') would fail at runtime with
                    # "Verb 'notify' not found".
                    val = f'{val}.msg(' + ', '.join(args) + ')'
                elif val in _PY_RECEIVERS:
                    # su and ou are Python objects, not MOO objects, so
                    # $string_utils:trim(s) is su.trim(s) -- call_verb would
                    # look for a verb on something that has none.
                    val = f'{val}.{name}(' + ', '.join(args) + ')'
                else:
                    inner = ''.join(f', {a}' for a in args)
                    val = f"call_verb({val}, '{name}'{inner})"
            elif self.at('['):
                self.next()
                # Inside an index, a bare $ is MOO for "the length of the
                # thing being indexed", so x[$] is the last element and
                # x[2..$] runs to the end.
                self.receiver.append(val)
                self.depth += 1
                try:
                    lo = self.expr()
                    if self.at('..'):
                        self.next()
                        hi = self.expr()
                        self.expect(']')
                        # 1-based, inclusive both ends -> [lo-1:hi]
                        val = f'{val}[{_minus1(lo)}:{hi}]'
                    else:
                        self.expect(']')
                        val = f'{val}[{_minus1(lo)}]'
                finally:
                    self.depth -= 1
                    self.receiver.pop()
            elif self.at('('):
                self.next()
                args = self.arglist(')')
                val = self.call(val, args)
            else:
                return val

    def arglist(self, close: str) -> List[str]:
        args = []
        if self.at(close):
            self.next()
            return args
        while True:
            if self.at('@'):
                self.next()
                args.append('*' + self._paren(self.expr))
            else:
                args.append(self._paren(self.expr))
            if self.at(','):
                self.next()
                continue
            self.expect(close)
            return args

    def call(self, fn: str, args: List[str]) -> str:
        joined = ', '.join(args)
        if fn == 'tonum':
            return f'int({joined})'
        if fn == 'parent':
            return f'{joined}.parent'
        if fn == 'children':
            return f'{joined}.children'
        if fn == 'listappend' and len(args) >= 2:
            return f'({args[0]} + [{args[1]}])'
        if fn == 'listinsert' and len(args) >= 2:
            return f'([{args[1]}] + {args[0]})'
        if fn == 'ctime':
            # MOO's ctime() is C's: epoch seconds to a readable string,
            # and with no argument, now.  Both are time.ctime exactly.
            self.needs_import.add('time')
            return f'time.ctime({joined})'

        if fn == 'strsub' and len(args) >= 3:
            return f'{args[0]}.replace({args[1]}, {args[2]})'
        if fn == 'toliteral':
            return f'repr({joined})'
        if fn == 'raise':
            # Python raises only as a statement, but MOO's raise() is an
            # expression and the common idiom puts it inside one:
            # `caller_perms().wizard || raise(E_PERM)`.  A call *is* an
            # expression, so moo_raise keeps the idiom rather than asking
            # for the verb to be restructured by hand.
            return f'moo_raise({joined})'
        if fn == 'caller_perms':
            # Not `caller`.  MOO's caller_perms() is the *owner of the
            # calling verb*, and `caller` is the calling object -- often
            # different, and the difference is what the check turns on,
            # since `caller_perms().wizard` guards real permissions.  This
            # mapped to `caller` only while the real builtin was missing.
            return 'caller_perms()'
        if fn == 'is_player':
            return f'{joined}.is_player'
        if fn == 'index' and len(args) >= 2:
            # MOO's index() is 1-based, 0 when absent.  Python's find() is
            # 0-based, -1 when absent, so +1 lines them up exactly.
            return f'({args[0]}.find({args[1]}) + 1)'
        if fn == 'time':
            # MOO's time() is epoch seconds.  `time` is not in the verb
            # namespace, so the import has to come with it -- the emitter
            # adds one at the top when this fires.  Asking a human to add
            # a line the translator knows it needs was never a judgement
            # call, and it was the fifth commonest mark in the corpus.
            self.needs_import.add('time')
            return 'time.time()'
        if fn == 'rindex' and len(args) >= 2:
            # As index(), but the last occurrence.  1-based, 0 when absent.
            return f'({args[0]}.rfind({args[1]}) + 1)'
        if fn == 'listset' and len(args) >= 3:
            # MOO's listset(list, value, index) returns a *new* list, so
            # the copy is the point -- writing through would mutate a list
            # the caller still holds.
            return f'moo_setitem(list({args[0]}), {args[2]}, {args[1]})'
        if fn == 'listdelete' and len(args) == 2:
            lst, i = args
            return f'({lst}[:{_minus1(i)}] + {lst}[{i}:])'
        if fn == 'setadd' and len(args) == 2:
            lst, x = args
            return f'({lst} if {x} in {lst} else {lst} + [{x}])'
        if fn == 'setremove' and len(args) == 2:
            lst, x = args
            return f'[_e for _e in {lst} if _e != {x}]'
        if fn in ('match', 'rmatch'):
            # A false friend, and the dangerous kind: MOO's match() is a
            # regex and this engine's match() matches objects, so passing
            # it through would compile and call the wrong function.
            # Renaming is not enough either -- MOO escapes with % and
            # treats ( as a literal, so the pattern itself needs
            # translating.  moo_match does both.
            return f'moo_{fn}({joined})'
        if fn == 'substitute':
            return f'moo_substitute({joined})'
        if fn == 'notify':
            # MOO's notify(who, text) is the raw output builtin.  The
            # MegaMOO spelling is who.msg(text), and the difference is not
            # cosmetic: msg is a verb and overridable per object, which is
            # how a deafened or filtered character stops hearing things.
            # notify() walks straight past that -- the same bug msg_room
            # had until it was fixed.
            if len(args) >= 2:
                who, text = args[0], args[1]
                if len(args) > 2:
                    self.note('notify() had extra arguments beyond the text; '
                              'msg() takes substitution kwargs instead')
                    self.marks += 1
                return f'{who}.msg({text})'
            self.note('notify() with unexpected arguments; check by hand')
            self.marks += 1
            return f'notify({joined})'
        if fn == 'pass':
            # `pass` is a Python keyword.  MegaMOO spells MOO's pass() as
            # pass_(), which is why that alias exists at all.
            return f'pass_({joined})'
        if fn == 'tostr':
            return ' + '.join(f'str({a})' for a in args) or "''"
        if fn == 'typeof':
            # Handled as a whole comparison in binary() when it is compared
            # against a type constant, which is how MOO always writes it.
            return f'typeof({joined})'
        if fn == 'valid':
            return f'({joined} != None)'
        if fn == 'toobj':
            return f'db.get_object({joined})'
        if fn in BUILTINS and BUILTINS[fn]:
            return f'{BUILTINS[fn]}({joined})'
        return f'{fn}({joined})'



def _assign(target: str, value: str) -> str:
    """
    An assignment statement, allowing for computed property names.

    `this.(verb) = x` translates its left side to getattr(this, verb),
    which cannot be assigned to.  Python spells that setattr().
    """
    m = re.fullmatch(r'getattr\((.*), (.*)\)', target, re.S)
    if m:
        return f'setattr({m.group(1)}, {m.group(2)}, {value})'
    if target in ('None', 'True', 'False'):
        # A sysref that maps to a constant rather than an object, being
        # written to: `$nothing = ""` in core setup code.  There is no
        # object here to store it on, and guessing at one would be worse
        # than saying so, so the line becomes a mark carrying the
        # original.  Rare -- two verbs in JHCore -- but it produced code
        # that did not compile at all.
        return f'{MARK} cannot assign to {target}  --  was: {target} = {value}'
    return f'{target} = {value}'


def _minus1(expr: str) -> str:
    """Shift a 1-based index to 0-based, folding the constant when we can."""
    s = expr.strip()
    if s.isdigit():
        return str(int(s) - 1)
    return f'{s} - 1'


def _wrap(text: str, width: int) -> List[str]:
    out, line = [], ''
    for word in text.split():
        if len(line) + len(word) + 1 > width:
            out.append(line)
            line = word
        else:
            line = f'{line} {word}'.strip()
    if line:
        out.append(line)
    return out or ['']



# ---------------------------------------------------------------------------
# Checking our own output
# ---------------------------------------------------------------------------

#: Names a verb can see that are not builtins: the context the engine
#: injects, plus the messaging kwargs.
_VERB_CONTEXT = {
    'pobj', 'this', 'caller', 'location', 'db', 'verb', 'args', 'argstr',
    'dobj', 'dobjstr', 'iobj', 'iobjstr', 'prep', 'switches', 'lhs', 'rhs',
    'arglist', 'kwargs', 'sub', 'dob', 'iob', 'uob', 'exclude', 'result',
    'su', 'string_utils', 'ou', 'object_utils', 'call_verb', 'search',
    'find', 'pass_', 'tell', 'player',
}


def _known_names() -> set:
    """Every name a verb body may reference without defining it."""
    import builtins as _py
    names = set()
    try:
        from . import builtins as _moo
        names |= set(_moo._get_builtin_ns_template())
    except Exception:          # importable standalone, e.g. under test
        pass
    try:
        # The E_* error values are injected by the compat layer rather
        # than being module-level builtins, so they have to be added
        # explicitly or every ported `! E_PERM' looks undefined.
        from .moo_compat import MOO_ERRORS
        names |= set(MOO_ERRORS)
    except Exception:
        pass
    try:
        # The ported utility objects and MOO's regex builtins are bound by
        # the namespace builder, not defined as module-level builtins, so
        # they have to be added or every ported $list_utils call looks
        # undefined.  Taken from the library itself rather than restated:
        # a hand-kept list would not fail loudly when it drifted, it would
        # just report working calls as broken.
        from . import moo_libs as _libs
        names |= set(_libs.__all__)
        names |= {'list_utils', 'command_utils', 'code_utils', 'perm_utils'}
        from . import moo_builtins as _mb
        names |= set(_mb.__all__)
    except Exception:
        pass
    return names | _VERB_CONTEXT | set(dir(_py))


def undefined_names(code: str) -> List[str]:
    """
    Names the translated code uses but nothing defines.

    This is the check that matters most, and the one that was missing.
    Verifying the output *parses* catches nothing useful: every bug found
    by hand so far -- notify, prepstr, verb_info, strsub -- produced
    perfectly valid Python that referred to something not there, and blew
    up the first time the verb ran.

    Args:
        code: Translated Python.

    Returns:
        Sorted names that are referenced but neither assigned nor known.
        Empty if the code does not parse, since then there is nothing
        meaningful to say.
    """
    body = '\n'.join(l for l in code.splitlines()
                      if not l.strip().startswith('#'))
    if not body.strip():
        return []
    try:
        tree = ast.parse('def _v():\n' +
                         '\n'.join('    ' + l for l in body.splitlines()))
    except SyntaxError:
        return []

    assigned, used = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            (assigned if isinstance(node.ctx, ast.Store) else used).add(node.id)
        elif isinstance(node, ast.arg):
            assigned.add(node.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                assigned.add((a.asname or a.name).split('.')[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            assigned.add(node.name)
    return sorted(used - assigned - _known_names())



def structure_of(source: str) -> dict:
    """Count the control flow in MOO source, from its tokens."""
    counts = {'if': 0, 'for': 0, 'while': 0, 'return': 0}
    try:
        for kind, text, _ in tokenise(source):
            if kind == 'name' and text in counts:
                counts[text] += 1
    except MooSyntaxError:
        return {}
    return counts


def structure_of_python(code: str) -> dict:
    """The same counts for the translated Python."""
    body = '\n'.join(l for l in code.splitlines()
                      if not l.strip().startswith('#'))
    counts = {'if': 0, 'for': 0, 'while': 0, 'return': 0}
    if not body.strip():
        return counts
    try:
        tree = ast.parse('def _v():\n' +
                         '\n'.join('    ' + l for l in body.splitlines()))
    except SyntaxError:
        return {}
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            counts['if'] += 1
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            counts['for'] += 1
        elif isinstance(node, ast.While):
            counts['while'] += 1
        elif isinstance(node, ast.Return):
            counts['return'] += 1
    return counts


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def port(source: str) -> PortResult:
    """
    Translate MOO source to Python.

    Args:
        source: MOO verb code.

    Returns:
        A :class:`PortResult`.  ``code`` is Python; ``notes`` lists what
        needs a human; ``marks`` counts the ``# PORT:`` lines left in.

    Raises:
        MooSyntaxError: The source is not MOO this can parse.  Nothing
            partial is returned -- a half-parsed verb would be worse than
            none.
    """
    p = Porter(source)
    body = p.block(0, ())
    lines = [ln for ln in body if ln.strip()]

    # Check our own output before handing it over.  Verifying that it
    # *parses* proves almost nothing -- every bug found in this translator
    # so far produced valid Python that named something not there and blew
    # up the first time the verb ran.  So the last step is to look up every
    # free name in the real verb namespace and mark the ones that are not
    # in it.
    # mooR proves its parser lost nothing by round-tripping: parse,
    # unparse, parse again, compare the trees.  Python cannot be unparsed
    # back to MOO, but the same property is worth checking -- a translation
    # claiming to be complete should still contain the control flow it
    # started with.  A mismatch means the parser quietly swallowed
    # something, which is the one failure that leaves no trace.
    if not p.marks:
        was, now = structure_of(source), structure_of_python('\n'.join(lines))
        if was and now:
            # `elseif` becomes a nested If in Python's tree, so if-counts
            # legitimately differ; the rest should match exactly.
            for kind in ('for', 'while', 'return'):
                if was.get(kind, 0) != now.get(kind, 0):
                    p.marks += 1
                    p.note(f'{was.get(kind, 0)} {kind} in the source but '
                           f'{now.get(kind, 0)} in the translation -- '
                           f'something was dropped, check this by hand')

    if p.needs_import:
        lines = [f'import {m}' for m in sorted(p.needs_import)] + [''] + lines

    for name in undefined_names('\n'.join(lines)):
        p.marks += 1
        p.note(f"'{name}' is not defined anywhere a verb can see; it is "
               f"probably a MOO builtin with no equivalent here")

    # A MARK can be emitted from a module-level helper that has no way to
    # reach the counter, and `clean` is built on the counter.  Reconciling
    # against the body means a mark cannot reach the output uncounted --
    # reporting a verb clean while it still carries a # PORT: line is the
    # one lie this whole tool exists to avoid.
    emitted = sum(1 for l in lines if l.lstrip().startswith(MARK))
    for l in lines:
        stripped = l.lstrip()
        if stripped.startswith(MARK):
            p.note(stripped[len(MARK):].strip())
    if emitted > p.marks:
        p.marks = emitted

    header = []
    if p.notes:
        header = [f'{MARK} {len(p.notes)} thing(s) here need a human:']
        header += [f'{MARK}   - {n}' for n in p.notes]
        header += ['']
    return PortResult('\n'.join(header + lines) + '\n', p.notes, p.marks)
