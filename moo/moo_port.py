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

``fork``, ``read()``, the backtick error-catch form (`` `x ! E_PERM' ``)
and ``try``/``except`` are left as marked comments rather than approximated.
They have no faithful one-line equivalent, and a plausible-looking wrong
translation is worse than an obvious hole.

Everything it emits that a human should check carries a ``# PORT:`` line, so
the residue is greppable.  A verb with no ``# PORT:`` markers is one the
translator believes it handled completely -- which is a claim about the
mechanical parts only, never about whether the logic is right.
"""

import re
from typing import List, Optional, Tuple

__all__ = ['port', 'PortResult', 'MooSyntaxError']

MARK = '# PORT:'

#: System references with a real equivalent.  Anything else becomes a
#: marked lookup rather than a guess at what the object was called.
SYSREFS = {
    'string_utils': 'su',
    'object_utils': 'ou',
    'list_utils': 'su',
    'player': 'pobj',
}

#: Mapped sysrefs that are Python objects rather than MOO objects.  A
#: ``:verb()`` call on one of these is a method call, not a verb call.
_PY_RECEIVERS = {'su', 'ou'}

#: MOO builtins that map straight onto Python.
BUILTINS = {
    'length': 'len', 'abs': 'abs', 'min': 'min', 'max': 'max',
    'random': 'random', 'floor': 'int', 'sqrt': 'sqrt',
    'tostr': None, 'toint': 'int', 'tofloat': 'float', 'toobj': None,
    'typeof': None, 'valid': None,
}

#: Constructs deliberately not translated.
REFUSED = {
    'fork': 'fork has no equivalent; use delay()/fork() with a code string, '
            'or restructure around suspend()',
    'read': 'read() blocks for player input; use an interactive session',
}


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
        self.depth = 0

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
                return out or ['    ' * indent + 'pass']
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
                return self._refuse(indent, 'try')
            if t == 'return':
                self.next()
                if self.at(';'):
                    self.next()
                    return [f'{pad}return']
                e = self.expr()
                self.eat_semi()
                return [f'{pad}return {e}']
            if t in ('break', 'continue'):
                self.next()
                self.eat_semi()
                return [f'{pad}{t}']

        # assignment or bare expression
        start = self.i
        lhs = self.expr()
        if self.at('='):
            self.next()
            rhs = self.expr()
            self.eat_semi()
            return [f'{pad}{lhs} = {rhs}']
        self.eat_semi()
        return [f'{pad}{lhs}']

    def _refuse(self, indent, word) -> List[str]:
        """Consume a construct we will not translate, and mark it."""
        pad = '    ' * indent
        depth = 0
        raw = []
        end = {'fork': 'endfork', 'try': 'endtry'}.get(word)
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
            lo = self.expr()
            self.expect('..')
            hi = self.expr()
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

    def while_stmt(self, indent) -> List[str]:
        pad = '    ' * indent
        self.expect('while')
        self.expect('(')
        cond = self._paren(self.expr)
        self.expect(')')
        out = [f'{pad}while {cond}:'] + self.block(indent + 1, ('endwhile',))
        if self.at_name('endwhile'):
            self.next()
            self.eat_semi()
        return out

    # -- expressions ------------------------------------------------------
    BIN = [
        (('||',), 'or'), (('&&',), 'and'),
        (('==', '!=', '<', '>', '<=', '>=', 'in'), None),
        (('+', '-'), None), (('*', '/', '%'), None),
    ]

    def expr(self) -> str:
        """A full expression: conditional, then assignment."""
        left = self.binary(0)

        # MOO's conditional, at any depth:  cond ? a | b
        if self.at('?'):
            self.next()
            a = self.expr()
            self.expect('|')
            b = self.expr()
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
                # Python's walrus binds plain names only, so assigning to a
                # property or an element *inside* an expression has no inline
                # form.  Mark it rather than emit something that will not
                # compile: the fix is to lift it to its own statement above.
                left = self.mark_expr(
                    'assignment inside an expression to something Python '
                    'cannot bind inline; lift it to its own statement',
                    f'{left} = {rhs}')
        return left

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
        """`expr ! E_FOO => fallback' -- caught, not translated."""
        raw = []
        self.next()
        while not self.at("'") and self.peek()[0] != 'eof':
            raw.append(self.next()[1])
        if self.at("'"):
            self.next()
        return self.mark_expr(
            'backtick error-catch: rewrite as try/except round the expression',
            '`' + ' '.join(raw) + "'")

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
        if k == 'name':
            if t == 'player':
                return 'pobj'
            return t
        raise MooSyntaxError(f'line {ln}: unexpected {t!r}')

    def postfix(self, val: str) -> str:
        while True:
            if self.at('.'):
                self.next()
                k, t, ln = self.next()
                if k == 'string':          # obj.("name") -- dynamic
                    self.mark('dynamic property name; getattr() it')
                    return f'getattr({val}, {t})'
                val = f'{val}.{t}'
            elif self.at(':'):
                self.next()
                name = self.next()[1]
                self.expect('(')
                args = self.arglist(')')
                if name == 'tell':
                    val = f'tell({val}' + (', ' + ', '.join(args) if args else '') + ')'
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
                lo = self.expr()
                if self.at('..'):
                    self.next()
                    hi = self.expr()
                    self.expect(']')
                    # 1-based and inclusive both ends -> [lo-1:hi]
                    val = f'{val}[{_minus1(lo)}:{hi}]'
                else:
                    self.expect(']')
                    val = f'{val}[{_minus1(lo)}]'
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
        if fn == 'raise':
            # `raise(E_PERM)` happens to be valid Python as a *statement* --
            # raise followed by a parenthesised expression -- but MOO also
            # uses it as an operand (`expr || raise(E_PERM)`), where Python
            # has no equivalent because raise is a statement.
            if self.depth:
                return self.mark_expr(
                    'raise() used inside an expression; Python can only '
                    'raise as a statement, so restructure this',
                    f'raise({joined})')
            return f'raise {joined}'
        if fn == 'caller_perms':
            return 'caller'
        if fn == 'is_player':
            return f'{joined}.is_player'
        if fn == 'index' and len(args) >= 2:
            # MOO's index() is 1-based, 0 when absent.  Python's find() is
            # 0-based, -1 when absent, so +1 lines them up exactly.
            return f'({args[0]}.find({args[1]}) + 1)'
        if fn == 'time':
            return 'time.time()'
        if fn == 'listdelete' and len(args) == 2:
            lst, i = args
            return f'({lst}[:{_minus1(i)}] + {lst}[{i}:])'
        if fn == 'setadd' and len(args) == 2:
            lst, x = args
            return f'({lst} if {x} in {lst} else {lst} + [{x}])'
        if fn == 'setremove' and len(args) == 2:
            lst, x = args
            return f'[_e for _e in {lst} if _e != {x}]'
        if fn == 'match':
            # A false friend, and the dangerous kind: MOO's match() is a
            # regex, MegaMOO's match() matches objects.  Passing it through
            # would compile and call the wrong thing.
            return self.mark_expr(
                "match() means regex in MOO but object-matching here; use "
                "re.search() or su, not match()", f'match({joined})')
        if fn == 'set_task_perms':
            return self.mark_expr(
                'set_task_perms() has no equivalent; permissions here follow '
                'the verb owner', f'set_task_perms({joined})')
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
            self.mark('typeof(): compare with isinstance() instead')
            return f'type({joined})'
        if fn == 'valid':
            return f'({joined} != None)'
        if fn == 'toobj':
            return f'db.get_object({joined})'
        if fn in BUILTINS and BUILTINS[fn]:
            return f'{BUILTINS[fn]}({joined})'
        return f'{fn}({joined})'


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

    header = []
    if p.notes:
        header = [f'{MARK} {len(p.notes)} thing(s) here need a human:']
        header += [f'{MARK}   - {n}' for n in p.notes]
        header += ['']
    return PortResult('\n'.join(header + lines) + '\n', p.notes, p.marks)
