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
    # MOO's integer limits.  A 64-bit server's values, because that is
    # what both this engine and a modern LambdaMOO use; a core comparing
    # against them is asking about the server it runs on, not the one it
    # was written on.
    'maxint': '9223372036854775807',
    'minint': '-9223372036854775808',
    'failed_match': 'FAILED_MATCH',
    'ambiguous_match': 'AMBIGUOUS_MATCH',
}

#: Verb-namespace variables that exist here under another name.  Every
#: other MOO name -- this, caller, verb, argstr, args, dobj, dobjstr, iobj,
#: iobjstr -- is spelled the same and needs no mapping.
VARIABLES = {
    'player': 'pobj',
    'prepstr': 'prep',
    # MOO's shorthand for the room you are in.  Marking it was the
    # translator being lazy: the fix is one word, it is the same word
    # every time, and a mark should mean "a human has to decide
    # something" rather than "I did not bother".
    'here': 'pobj.location',
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

#: Constructs deliberately not translated.  Empty now: read() used to be
#: here, and everything else that was ever in it turned out to have an
#: honest translation.  Kept because the mechanism is still the right
#: answer for anything that genuinely has none.
REFUSED = {}


#: Comparisons whose Python spelling means something else, because MOO
#: compares strings without regard to case.  Only these are skippable
#: when neither operand can be a string.
MOO_CMP = {'==': 'moo_eq', '!=': 'moo_ne', '<': 'moo_lt', '<=': 'moo_le',
           '>': 'moo_gt', '>=': 'moo_ge'}

#: Arithmetic whose Python spelling means something else.  These are
#: *never* skippable: the difference is about integers, not strings, so
#: `7 / 2` -- where both operands are plainly numbers -- is exactly the
#: case that goes wrong.  MOO gives 3, Python's / gives 3.5, and Python's
#: // gives 3 but rounds the wrong way on negatives.
MOO_ARITH = {'/': 'moo_div', '%': 'moo_mod'}

_NUMERIC_CALLS = ('len(', 'abs(', 'min(', 'max(', 'int(', 'float(',
                  'len (', 'time.time(', 'random(', 'typeof(')


def _provably_not_string(text: str) -> bool:
    """
    Whether *text* cannot possibly evaluate to a string.

    Used to keep the readable spelling where it is safe to.  MOO compares
    strings without regard to case, so ``==`` has to go through moo_eq
    whenever a string might be involved -- but ``i == 0`` and
    ``len(x) > 3`` never involve one, and rewriting those would make
    every translation harder to read for no gain.

    One side is enough.  The two languages only disagree when *both*
    operands are strings, so a comparison with a number on either side can
    keep Python's operator -- which is why `i == 0` stays readable while
    `a == b`, where neither side is knowable, does not.

    Deliberately conservative: it says no unless it is certain, because a
    wrong yes here reinstates exactly the silent bug the helper exists to
    remove.

    Args:
        text: Translated Python for one operand.

    Returns:
        True only when the value is certainly numeric or an object.
    """
    t = text.strip().strip('()').strip()
    if not t:
        return False
    if re.fullmatch(r'-?\d+(\.\d+)?([eE][-+]?\d+)?', t):
        return True
    if t in ('None', 'True', 'False'):
        return True
    if t.startswith('#') and t[1:].lstrip('-').isdigit():
        return True
    if t.startswith(_NUMERIC_CALLS) and t.endswith(')'):
        return True
    # An arithmetic expression over things that are themselves numeric.
    if re.fullmatch(r'[-+*/%\s\d().]+', t):
        return True
    return False


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
  | (?P<number>\d+\.\d+(?:[eE][-+]?\d+)?|\d+[eE][-+]?\d+|\d+)
  | (?P<name>[A-Za-z_]\w*)
  | (?P<range>\.\.)
  | (?P<op>>>>|<<|>>|&\.|\|\.|\^\.|<=|>=|==|!=|&&|\|\||=>|[-+*/%^<>=!?|:.,;()\[\]{}@`'])
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
    def __init__(self, src: str, resolve=None, maps: bool = False):
        #: Answers "is $name defined on #0?".  port() supplies the
        #: running server's.  None when translating outside one --
        #: under test, or from a script -- and then every $reference is
        #: taken on trust, because an absent database is not evidence
        #: that an object is missing.
        self._resolve = resolve
        #: Whether the source dialect has maps.  Stock LambdaMOO 1.8 does
        #: not -- they are a ToastStunt addition -- so a subscript there
        #: is always a 1-based list or string index and shifts directly.
        #: Where maps exist the two cannot be told apart by looking, so
        #: every subscript has to go through moo_index and decide at run
        #: time.  That is uglier and slower, which is why it is not the
        #: default: it would be paid on every LambdaCore subscript for a
        #: type those databases cannot contain.
        self.maps = maps
        self.toks = tokenise(src)
        self.i = 0
        self.notes: List[str] = []
        #: One per note, parallel: a snippet to find it by, or None.
        self.locators: List[Optional[str]] = []
        self.marks = 0
        #: Modules the translation needs that a verb namespace
        #: does not already provide.  Emitted as imports rather
        #: than asked for in a note.
        self.needs_import = set()
        self.depth = 0
        self.receiver: List[str] = []
        #: Labels of the loops we are inside, innermost last.  MOO lets
        #: break and continue name a loop; Python does not, so the label
        #: only matters when it is not the innermost one.
        self.loops: List[Optional[str]] = []
        #: Labels some break or continue actually named.  A handler is
        #: only wrapped around a loop when one was, so the ordinary loop
        #: keeps its ordinary shape.
        self.labels_used = set()

    def sysref_resolves(self, name: str, default: bool = True) -> bool:
        """
        Whether ``$name`` is defined on #0 right now.

        Args:
            name: The reference, without the ``$``.
            default: What to answer with no resolver to ask.  True when
                deciding whether to *mark* -- an absent database is not
                evidence that an object is missing.  False when deciding
                whether to prefer the database over a shim, since with no
                database there is nothing to prefer.
        """
        if self._resolve is None:
            return default
        try:
            return bool(self._resolve(name))
        except Exception:
            # A resolver that errors tells us nothing about the
            # reference, so it must not be read as an absence.
            return True

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

    def note(self, msg, find=None):
        """
        Record something a human should see.

        Args:
            msg: What to tell them.
            find: A snippet of the *emitted Python* this note is about.
                port() looks it up afterwards and puts the line number on
                the front, which is the difference between "something in
                this verb needs attention" and a place to put the cursor.
                The verb is Python by the time anyone reads it, so the
                output line is the useful one -- the MOO line it came from
                no longer exists to be edited.
        """
        if msg not in self.notes:
            self.notes.append(msg)
            self.locators.append(find)

    def mark(self, msg, find=None) -> str:
        """Mark something for a human.  Safe only at end of statement."""
        self.marks += 1
        self.note(msg, find=find)
        return f"{MARK} {msg}"

    def mark_expr(self, msg: str, original: str, find=None) -> str:
        """
        Mark something *inside* an expression.

        A `#` comment cannot go here -- it would comment out the rest of
        the line and the result would not compile.  So the placeholder is
        a bare None and the original is carried in the notes, which the
        header reproduces.
        """
        self.marks += 1
        self.note(f'{msg}  --  was: {original}', find=find)
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
                # A raise as the whole statement.  It goes through the
                # same helper the expression form uses -- `raise E_TYPE,
                # "msg"` is Python 2 and does not compile, and MOO's
                # raise() takes up to three arguments in any case.
                self.next()
                self.expect('(')
                what = self._paren(lambda: ', '.join(self.arglist(')')))
                self.eat_semi()
                return [f'{pad}moo_raise({what})']
            if t in ('break', 'continue'):
                self.next()
                # `break searching;` names the loop to leave.  The name was
                # being left behind as a statement of its own -- dead code
                # after the break, and an undefined name on top of it.
                label = None
                if self.peek()[0] == 'name' and self.peek(1)[1] == ';':
                    label = self.next()[1]
                self.eat_semi()
                if label and label != (self.loops[-1] if self.loops else None):
                    # Aimed at a loop further out.  Python's break leaves
                    # only the innermost one, so emitting it plain would
                    # carry on running the outer loop.  Raising unwinds to
                    # the right place on its own; while_stmt and for_stmt
                    # generate the handler beside the loop that owns the
                    # label.
                    if label in self.loops:
                        self.labels_used.add((label, t))
                        return [f'{pad}raise MooLoopSignal({label!r}, {t!r})']
                    self.mark(f'{t} {label!r} names a loop that is not open '
                              f'here; nothing encloses this to leave')
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

    def try_scatter(self, want_expr: bool = False):
        """
        Parse `{a, ?b = d, @rest} = expr`, or give up and return None.

        MOO's scatter has three item kinds: required, optional (with an
        optional default), and rest.  Python's unpacking *statement* covers
        required and rest but has nothing for optionals -- it raises when
        the right side is too short rather than leaving a name unbound.

        That is a limit of the one-line form, not of Python, so when there
        are optionals the whole thing is expanded into a run of statements
        that index the value directly.  Refusing it was expensive out of
        proportion to the construct: an unbound target is an undefined name
        everywhere it is read afterwards, so a single unhandled `?width =
        79` marked the verb several times over.

        An optional with no default is left as None.  MOO leaves it
        genuinely unbound and raises E_VARNF on a read, which Python cannot
        express without restructuring the whole verb, and None matches what
        this engine already does everywhere else a value is absent.
        """
        self.expect('{')
        # Kept in source order, because the order is what decides how a
        # short right-hand side is distributed.
        items = []
        while not self.at('}'):
            if self.at('@'):
                self.next()
                items.append(('rest', self.next()[1], None))
            elif self.at('?'):
                self.next()
                nm = self.next()[1]
                default = None
                if self.at('='):
                    self.next()
                    default = self._paren(self.expr)
                items.append(('opt', nm, default))
            else:
                k, t, _ = self.peek()
                if k != 'name':
                    return None
                self.next()
                items.append(('req', t, None))
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

        names = [nm for kind, nm, _ in items if kind != 'rest']
        optional = [(nm, d) for kind, nm, d in items if kind == 'opt']
        rest = next((nm for kind, nm, _ in items if kind == 'rest'), None)
        required = [nm for kind, nm, _ in items if kind == 'req']

        if not optional:
            # No optionals: Python's own unpacking says exactly this, and
            # it raises on a length mismatch just as MOO does.
            target = ', '.join(_safe_name(n) for n in required)
            if rest:
                target = ', '.join(filter(None, [target, f'*{_safe_name(rest)}']))
            if not target:
                return None if want_expr else [f'# {value}']
            if want_expr:
                # Plain unpacking has no expression form, so this one goes
                # through the general path instead.
                self._scatters = getattr(self, '_scatters', 0) + 1
                tmp = f'_scatter_{self._scatters}'
                lines = [f'{tmp} = {value}']
                lines += [f'{_safe_name(nm)} = {tmp}[{i}]'
                          for i, nm in enumerate(required)]
                if rest:
                    lines.append(
                        f'{_safe_name(rest)} = {tmp}[{len(required)}:]')
                return self._assignments_as_expression(lines, tmp)
            return [f'{target} = {value}']

        # Two shapes, and the difference is only about readability.
        #
        # Written the usual way -- required, then optionals, then a rest
        # target -- each binding is a plain indexed read and says so.  When
        # the kinds interleave, the fill is no longer positional and the
        # general rule applies instead: required targets are satisfied
        # first wherever they sit, and what is left over feeds the
        # optionals in order.  That was previously refused as "ambiguous",
        # which was wrong -- MOO specifies it; I was describing my parser,
        # not the language.
        kinds = [kind for kind, _, _ in items]
        tidy = (kinds == sorted(kinds, key=('req', 'opt', 'rest').index)
                and kinds.count('rest') <= 1)

        # The value is bound to a name first when it is not already one, so
        # a right side with side effects is evaluated once rather than once
        # per target.
        if value.isidentifier() and not want_expr:
            src = value
            out = []
        else:
            # In expression position the temp is not an optimisation, it
            # is required: the whole thing evaluates to the right-hand
            # side, and a rest target routinely rebinds the very name it
            # was read from -- `{?sfc, @todo} = todo`.  Without the temp
            # the result would be the list after the assignment rather
            # than before it.
            self._scatters = getattr(self, '_scatters', 0) + 1
            src = f'_scatter_{self._scatters}'
            out = [f'{src} = {value}']

        if not tidy:
            spec = ', '.join(
                "('rest',)" if kind == 'rest' else
                "('req',)" if kind == 'req' else
                f"('opt', {d if d else 'None'})"
                for kind, _, d in items)
            self._scatters = getattr(self, '_scatters', 0) + 1
            got = f'_scattered_{self._scatters}'
            out.append(f'{got} = moo_scatter({src}, [{spec}])')
            out += [f'{_safe_name(nm)} = {got}[{i}]'
                    for i, (_, nm, _) in enumerate(items)]
            return self._assignments_as_expression(out, src) if want_expr else out

        for i, nm in enumerate(required):
            out.append(f'{_safe_name(nm)} = {src}[{i}]')
        for j, (nm, default) in enumerate(optional):
            i = len(required) + j
            out.append(f'{_safe_name(nm)} = {src}[{i}] if len({src}) > {i} '
                       f'else {default if default else "None"}')
        if rest:
            out.append(f'{_safe_name(rest)} = {src}[{len(names)}:]')
        return self._assignments_as_expression(out, src) if want_expr else out

    @staticmethod
    def _assignments_as_expression(lines, result):
        """
        Fold ``name = value`` lines into one expression that binds them.

        Args:
            lines: Statements, each ``target = source``.
            result: What the whole expression should evaluate to.

        Returns:
            A tuple display of walrus bindings, indexed to yield *result*.
        """
        parts = []
        for line in lines:
            name, _, rhs = line.partition(' = ')
            parts.append(f'({name.strip()} := {rhs})')
        return '(' + ', '.join(parts) + f', {result})[-1]'

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
        var = _safe_name(self.next()[1])
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
        # A for loop's *variable* is its label -- `for x in (l) ... break
        # x; ... endfor` is MOO's spelling.  Pushing None here instead
        # made every one of those look like a break out of an enclosing
        # loop, which is the opposite of what it is.
        self.loops.append(var)
        body = self.block(indent + 1, ('endfor',))
        self.loops.pop()
        out = self._wrap_labelled(var, indent, head, body)
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

    def _wrap_labelled(self, label, indent, head, body):
        """
        Give a loop the handlers for breaks and continues aimed at it.

        The two go in different places, which is the whole point of doing
        it this way rather than with a flag.

        A ``break outer`` has to leave the loop, so its handler wraps the
        loop.  A ``continue outer`` has to end this iteration and start
        the next, so its handler wraps the loop *body* -- swallowing the
        signal there lets the body finish and the loop carry on, which is
        what continue means.

        Both handlers re-raise anything not meant for them, so a signal
        aimed several levels out passes cleanly through the ones between.

        Only emitted when something actually named the label.  MOO labels
        loops far more often than it jumps out of them non-locally, and
        wrapping every labelled loop would put a try around code that
        never needed one.

        Args:
            label: The loop's name, or None.
            indent: Its indentation level.
            head: The `while ...:` or `for ...:` line.
            body: The loop body, already indented one level in.

        Returns:
            The loop, wrapped as required.
        """
        pad = '    ' * indent
        wants_break = (label, 'break') in self.labels_used
        wants_continue = (label, 'continue') in self.labels_used
        self.labels_used.discard((label, 'break'))
        self.labels_used.discard((label, 'continue'))

        if wants_continue:
            body = ([f'{pad}    try:'] +
                    ['    ' + l for l in body] +
                    [f'{pad}    except MooLoopSignal as _sig:',
                     f"{pad}        if _sig.label != {label!r} or "
                     f"_sig.kind != 'continue':",
                     f'{pad}            raise'])
        out = [head] + body
        if wants_break:
            out = ([f'{pad}try:'] + ['    ' + l for l in out] +
                   [f'{pad}except MooLoopSignal as _sig:',
                    f"{pad}    if _sig.label != {label!r} or "
                    f"_sig.kind != 'break':",
                    f'{pad}        raise'])
        return out

    def while_stmt(self, indent) -> List[str]:
        pad = '    ' * indent
        self.expect('while')
        # MOO 1.8 allows a loop label: `while searching (queue)`.  The
        # label alone is harmless -- it only matters if a break or continue
        # names an *enclosing* loop, and that is caught at the break
        # itself, where it can be described precisely.  Warning here
        # marked every labelled loop, including the great majority whose
        # breaks target the loop they are already in.
        label = None
        if self.peek()[0] == 'name' and self.peek(1)[1] == '(':
            label = self.next()[1]
        self.expect('(')
        cond = self._paren(self.expr)
        self.expect(')')
        self.loops.append(label)
        body = self.block(indent + 1, ('endwhile',))
        self.loops.pop()
        out = self._wrap_labelled(label, indent, f'{pad}while {cond}:', body)
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
    #: Binary operators, loosest first.  The order is mooR's precedence
    #: table (crates/compiler/src/precedence.rs), which is the closest
    #: thing to a specification of the language that exists.
    #:
    #: The bitwise level and `^.` are mooR extensions rather than
    #: LambdaMOO 1.8, and they are here because a core written for mooR
    #: otherwise fails to parse outright.  Note `^` is exponentiation and
    #: `^.` is xor -- mooR spells them apart precisely because the two
    #: would collide, and reading `^` as xor would turn every ported
    #: `10 ^ i` into a silently wrong number.
    BIN = [
        (('||', '&&'), None),
        (('|.',), None), (('^.',), None), (('&.',), None),
        (('==', '!=', '<', '>', '<=', '>=', 'in'), None),
        (('<<', '>>', '>>>'), None),
        (('+', '-'), None), (('*', '/', '%'), None),
        (('^',), None),
    ]

    #: How MOO spells an operator vs how Python does.
    OPS = {'|.': '|', '^.': '^', '&.': '&', '>>>': '>>', '^': '**'}

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
                elif target[0] == 'sys':
                    left = f'set_sysobj({target[1]}, {rhs})'
                elif target[0] == 'prop':
                    left = f'moo_setprop({target[1]}, {target[2]}, {rhs})'
                else:
                    # An indexed write has to rebind, because MOO lists are
                    # values -- see _assign.  In expression position that
                    # needs a form which both rebinds and yields, and there
                    # are two: the walrus for a plain name, and moo_setprop
                    # for a property, which returns what it stored.
                    seq, index = target[1], target[2]
                    rebound = self._rebind(
                        seq, f'moo_listset({seq}, {index}, {rhs})')
                    if rebound is None:
                        # Nowhere to store the new list, so MOO's value
                        # semantics are genuinely lost here rather than
                        # merely untranslated.  Worth saying.
                        left = self.mark_expr(
                            'indexed assignment inside an expression whose '
                            'container cannot be rebound; MOO would leave '
                            'the original list untouched and this will not',
                            f'{seq}[{index}] = {rhs}')
                    else:
                        left = rebound
        return left

    def _is_scatter_expr(self) -> bool:
        """
        Whether the ``{`` just consumed opens a scatter, not a list.

        The two are only told apart by what follows the closing brace: a
        bare ``=`` makes it an assignment target.  Looking for ``?`` or
        ``@`` inside is not enough, because ``{@args, 1}`` is an ordinary
        list splat and extremely common -- treating those as scatter
        marked a large fraction of the corpus and cost eight points of
        clean rate before the measurement caught it.
        """
        saved, depth = self.i, 0
        try:
            while True:
                k, t, _ = self.peek()
                if k == 'eof':
                    return False
                if t in '([{':
                    depth += 1
                elif t == '}' and depth == 0:
                    self.next()
                    return self.at('=') and self.peek(1)[1] != '='
                elif t in ')]}':
                    depth -= 1
                self.next()
        finally:
            self.i = saved

    def _rebind(self, target: str, value: str):
        """
        An *expression* that stores *value* back into *target*.

        MOO's indexed assignment rebinds rather than writing through, and
        in expression position that needs a form which both stores and
        yields.  There are three, and which one applies depends on what
        the container is: the walrus for a plain name, moo_setprop for a
        property, set_sysobj for a ``$ref``.

        It recurses, because a nested target has to be rebuilt from the
        inside out and then stored at the outermost level -- rebinding
        only the inner list would mutate in place one level down, which
        is the bug this is here to avoid.

        Args:
            target: Translated Python for the container.
            value:  Translated Python for what it should become.

        Returns:
            The expression, or None when there is nowhere to store it --
            assigning into the result of a call, for instance.
        """
        if target.isidentifier():
            return f'({target} := {value})'
        parts = self._split_target(target)
        if parts is None:
            return None
        if parts[0] == 'prop':
            return f'moo_setprop({parts[1]}, {parts[2]}, {value})'
        if parts[0] == 'sys':
            return f'set_sysobj({parts[1]}, {value})'
        seq, index = parts[1], parts[2]
        return self._rebind(seq, f'moo_listset({seq}, {index}, {value})')

    @staticmethod
    def _split_target(text: str):
        """
        Take apart an already-translated assignment target.

        Args:
            text: Translated Python for the left side, e.g. ``this.name``
                or ``lst[i - 1]``.

        Returns:
            ``('prop', obj, name)``, ``('item', seq, index)``, or None if
            it is not a shape that can be written through a helper.  For
            'prop' the *name* is already Python source -- quoted for a
            plain ``a.b``, left as an expression for MOO's computed
            ``a.(expr)`` form -- so the caller does not have to know which
            it came from.

        The bracket scan counts depth rather than searching for the first
        ``[``, because the container is itself an expression and may carry
        brackets of its own -- ``x[1][2]`` must split at the last pair.
        """
        # MOO's computed property access, a.(expr), has already become a
        # getattr() by the time it reaches here.  The statement form turns
        # that into setattr(); in an expression it needs the helper.
        m = re.fullmatch(r'sysobj\((.*)\)', text, re.S)
        if m:
            return ('sys', m.group(1), None)
        m = re.fullmatch(r'getattr\((.*), (.*)\)', text, re.S)
        if m:
            return ('prop', m.group(1), m.group(2))
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
            return ('prop', head, repr(name))
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
                # Not Python's `in`.  MOO's yields a 1-based index rather
                # than a boolean, which was already handled -- and
                # compares with MOO's equality, which folds case, which
                # was not.  `dobjstr in this.aliases` is the commonest
                # use there is, and it was failing on any capitalisation
                # the author had not anticipated.
                left = f'moo_in({left}, {right})'
                continue
            if k == 'op' and t in ops:
                op = self.next()[1]
                # Exponentiation groups to the right in both languages, so
                # 2^3^2 is 2^(3^2).  Recursing at the same level rather
                # than the next one is what makes that true; the loop
                # below is left-associative, which is right for everything
                # else and wrong only for this.
                right = (self.binary(level) if op == '^'
                         else self.binary(level + 1))
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
                if op in MOO_ARITH:
                    left = f'{MOO_ARITH[op]}({left}, {right})'
                    continue
                if op in MOO_CMP and not (_provably_not_string(left) or
                                          _provably_not_string(right)):
                    # MOO compares strings without regard to case, and
                    # nothing about `x == "north"` looks wrong until
                    # someone types "North".  Skipped only where neither
                    # side can be a string, to keep `i == 0` readable.
                    left = f'{MOO_CMP[op]}({left}, {right})'
                    continue
                left = f'{left} {word or self.OPS.get(op, op)} {right}'
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
            num = t[1:].strip()
            if num.startswith('-'):
                # MOO's negative object numbers are its "no object"
                # values -- #-1 is $nothing, #-2 ambiguous, #-3 failed.
                # They are not objects and there is nothing to look up,
                # so they map to the same things the $ spellings do.
                #
                # Emitting `#-1` produced code that did not compile at
                # all, because the objref preprocessor reads a `#` not
                # followed by a digit as a comment.
                return {'-1': 'None', '-2': 'AMBIGUOUS_MATCH',
                        '-3': 'FAILED_MATCH'}.get(num, 'None')
            return '#' + num
        if k == 'sysref':
            name = t[1:]
            if name in SYSCONSTANTS:
                return SYSCONSTANTS[name]
            # The database's own object wins over the shim.
            #
            # These remaps exist so a single verb can be ported into a
            # world that has no $string_utils.  A database that *does*
            # have one -- every real core ships its own, with far more
            # methods than the port here -- was getting it silently
            # replaced by MegaMOO's Python module, which is both wrong
            # and worse: LambdaCore's #20 has all 173 methods and the
            # shim has 59.
            #
            # So the shim is the fallback, not the default.  With no
            # resolver at all -- porting one verb offline -- nothing
            # changes, which is the case the remaps were written for.
            if self.sysref_resolves(name, default=False):
                return f'sysobj({name!r})'
            if name in SYSREFS:
                return SYSREFS[name]
            # `$foo` is not special syntax in MOO -- it is `#0.foo`, a
            # property on the system object -- and this engine already
            # works the same way, carrying $chair and $item on #0 today.
            # So the translation never varied; what varies is whether it
            # will resolve, and that is a question the live database can
            # answer rather than something to guess at.  It used to be
            # marked unconditionally, which is a strange thing for a tool
            # that runs inside the server it is porting into.
            if not self.sysref_resolves(name):
                self.mark_expr(
                    f'${name} is not defined on #0; whatever it refers to '
                    f'has not been brought across yet',
                    f'${name}', find=f'sysobj({name!r})')
            return f'sysobj({name!r})'
        if t == '(':
            e = self._paren(self.expr)
            self.expect(')')
            return f'({e})'
        if t == '{':
            if self._is_scatter_expr():
                # `while ({?sfc, @todo} = todo)` -- MOO's scatter is an
                # expression, and LambdaCore uses one as a loop condition.
                #
                # I had this filed as impossible, on the grounds that
                # Python cannot bind names from inside an expression.  It
                # cannot bind from a *call*, which is not the same claim:
                # the walrus binds, and a tuple display evaluates its
                # elements left to right.  So the same fill the statement
                # form does fits in one expression, ending with the
                # right-hand side, because that is what MOO's scatter
                # evaluates to.
                #
                # It is not pretty.  The alternative was losing the loop.
                self.i -= 1
                expr = self.try_scatter(want_expr=True)
                if expr is None:
                    return self.mark_expr(
                        'scatter inside an expression that could not be '
                        'read as one', '{...}')
                return expr
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
                if keyword.iskeyword(t) or t in ('None', 'True', 'False'):
                    # A property whose name Python has claimed.  MOO cores
                    # define `and`, `in`, `for` and `return` as ordinary
                    # properties, and ToastStunt's waifs use `.class`.
                    #
                    # Unlike a *variable* of the same name, this cannot be
                    # renamed: the property really is called that, and
                    # `o.class_` would read something that does not exist.
                    # getattr() is exact and needs no cooperation from
                    # anything else.
                    val = f'getattr({val}, {t!r})'
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
                        val = (f'moo_index({val}, {lo})' if self.maps
                               else f'{val}[{_minus1(lo)}]')
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
            # listset(list, value, index) returns a *new* list; writing
            # through would mutate one the caller still holds.  The index
            # is MOO's, so it shifts like every other subscript -- it was
            # being passed straight through, which put the write one place
            # too far along.
            return f'moo_listset({args[0]}, {_minus1(args[2])}, {args[1]})'
        if fn == 'listdelete' and len(args) == 2:
            lst, i = args
            return f'({lst}[:{_minus1(i)}] + {lst}[{i}:])'
        # setadd and setremove used to be expanded inline.  Both forms
        # were wrong: the setadd one compared with Python's `in` and the
        # setremove one with `!=`, where MOO uses its own equality and
        # folds case, so `setremove(l, "Foo")` missed "foo".  The
        # comprehension had a second problem -- a walrus anywhere in the
        # list it iterated made the verb fail to compile, which is how
        # this was found.  The builtins do it properly.
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
            # MOO's notify(who, text) is the raw output builtin; the
            # MegaMOO spelling is who.msg(text), and the difference is not
            # cosmetic -- msg is a verb and overridable per object, which
            # is how a deafened or filtered character stops hearing
            # things.  notify() walks straight past that.
            #
            # It goes through a helper rather than becoming a bare
            # who.msg(text) because MOO's notify *returns* whether the
            # line was accepted, and cores loop on it:
            # `while (!notify(conn, line, 1)) suspend(0); endwhile`.
            # msg() returns None, so the direct translation turns that
            # retry loop into an infinite one.  moo_notify returns 1.
            #
            # The third argument is MOO's no-flush flag, about an output
            # queue this engine does not have.  It is accepted and
            # ignored, which is why extra arguments no longer need saying.
            if len(args) >= 2:
                return f'moo_notify({joined})'
            return f'moo_notify({joined})'
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
        if fn.isidentifier() and fn not in _known_names():
            # A builtin this server does not have.  Emitting the bare name
            # produced code that compiled and then died on a NameError
            # naming a Python identifier, which tells a MOO author
            # nothing.  Routing it through call_function keeps the verb
            # loadable and turns the failure into a MOO error naming the
            # builtin -- and only on the path that actually calls it, so a
            # verb whose unsupported branch is never taken simply works.
            #
            # This is mooR's trick for textdump imports
            # (compile_options.call_unsupported_builtins), and it is worth
            # copying for the same reason: refusing to load a whole verb
            # over one unreachable line helps nobody.
            #
            # Still marked.  mooR imports databases unattended, where a
            # runtime failure is the only option; @port has a human
            # watching, and telling them now is better than telling them
            # later.
            #
            # Only a bare name can be a builtin.  When the callee is an
            # expression -- `$core_object_info(...)`, which calls whatever
            # #0 holds under that name -- the call is already correct and
            # wrapping it would break a working translation.
            self.mark_expr(
                f'{fn}() is not a builtin here; it is wrapped in '
                f'call_function so the verb still loads, and will raise '
                f'naming {fn} if that line runs',
                f'{fn}({joined})', find=f'call_function({fn!r}')
            args = f', {joined}' if joined else ''
            return f'call_function({fn!r}{args})'
        return f'{fn}({joined})'



def _assign(target: str, value: str) -> str:
    """
    An assignment statement, in MOO's terms rather than Python's.

    Two of MOO's assignment forms do not survive a direct translation.

    ``this.(verb) = x`` translates its left side to ``getattr(this,
    verb)``, which cannot be assigned to; Python spells that ``setattr``.

    ``l[1] = v`` is the one that matters more, because the direct
    translation compiles and runs.  **MOO lists are values, not
    references.**  The assignment builds a new list and rebinds the
    variable, so after ``l2 = l1; l2[1] = 5;`` the list ``l1`` is
    untouched.  Python's lists are references, so ``l2[0] = 5`` reaches
    through and changes ``l1`` too -- a bug that only shows when
    something else still holds the original, and then nowhere near the
    line that caused it.  So an indexed assignment becomes a rebind
    through moo_listset.

    The rebinding recurses, which is what makes nesting come out right:
    ``a[i][j] = v`` must rebuild the inner list *and* store it back into
    the outer one, and rebinding only the inner would mutate in place
    again one level down.

    Args:
        target: Translated Python for the left side.
        value:  Translated Python for the right side.

    Returns:
        A single Python statement.
    """
    parts = Porter._split_target(target)
    if parts and parts[0] == 'item':
        seq, index = parts[1], parts[2]
        return _assign(seq, f'moo_listset({seq}, {index}, {value})')

    m = re.fullmatch(r'getattr\((.*), (.*)\)', target, re.S)
    if m:
        return f'setattr({m.group(1)}, {m.group(2)}, {value})'
    m = re.fullmatch(r"sysobj\((.*)\)", target, re.S)
    if m:
        # `$foo = v` is `#0.foo = v` -- ordinary configuration, which
        # cores do in their setup verbs.  It needs a function only
        # because the read side is a call and Python cannot assign to one.
        return f'set_sysobj({m.group(1)}, {value})'
    if target in ('None', 'True', 'False'):
        # Writing to something that translated to a constant.  In practice
        # this is `$shutdown_message = ""` -- an unknown sysref, whose
        # placeholder is None, being assigned to.
        #
        # It is emitted as a plain comment rather than a MARK, because the
        # unknown sysref has already been marked where it was read.  One
        # problem should be reported once; a second mark here made the
        # count say two things were wrong when only one was.  The original
        # is kept so the line is not silently lost.
        return f'# cannot assign to {target}  --  was: {target} = {value}'
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
        try:
            # Optional: only present in a tree that ports from a server
            # with file builtins.
            from . import moo_files as _mf
            names |= set(_mf.__all__)
        except ImportError:
            pass
        # read() is engine machinery rather than a compatibility shim --
        # it takes the baton off the verb thread -- so it is bound by the
        # namespace builder and has to be named here.
        names.add('read')
    except Exception:
        pass
    return names | _VERB_CONTEXT | set(dir(_py))


#: The utility objects @port remaps `$name` onto, and what they were.
_SHIM_NAMES = {'su': 'string_utils', 'ou': 'object_utils', 'lu': 'list_utils',
               'cu': 'command_utils', 'cdu': 'code_utils', 'pu': 'perm_utils'}

_SHIM_CALL = re.compile(r'\b(su|ou|lu|cu|cdu|pu)\.(\w+)')


def _missing_shim_methods(code: str):
    """
    Calls to utility methods the ports of those objects do not have.

    This is the hole the undefined-name check cannot see.  ``$string_utils
    :pronoun_sub`` becomes ``su.pronoun_sub`` -- an *attribute* access, and
    the name `su` is perfectly well defined -- so a method that does not
    exist looks exactly like one that does, and the verb translates clean
    and then fails the first time it runs.

    Across the two stock cores that was roughly one clean verb in six.  It
    is the difference between "this translated" and "this will work", and
    conflating the two made the first number flatter than it deserved.

    Args:
        code: Translated Python, ``# PORT:`` lines and all.

    Returns:
        Sorted ``(receiver, method)`` pairs that will not resolve.
    """
    body = '\n'.join(l for l in code.splitlines()
                      if not l.strip().startswith(MARK))
    shims = {}
    try:
        from .string_utils import su
        from . import object_utils as ou
        from .moo_libs import lu, cu, cdu, pu
        shims = {'su': su, 'ou': ou, 'lu': lu, 'cu': cu, 'cdu': cdu, 'pu': pu}
    except Exception:          # importable standalone, e.g. under test
        return []
    # A verb may bind one of these names itself.  LambdaCore writes
    # `su = $string_utils;` and then `su:match_string(...)`, which
    # translates correctly to a call on the imported object -- but it
    # looks exactly like a call on the bundled shim, and reporting it
    # sent people to fix code that was already right.
    #
    # An assignment to the name anywhere in the verb is enough to say the
    # receiver is local.  Being wrong in this direction costs a missed
    # warning; being wrong in the other cries wolf, which is worse for a
    # tool whose whole value is that its marks mean something.
    bound = set(re.findall(r'^\s*(\w+)\s*=(?!=)', body, re.M))

    out = set()
    for recv, meth in _SHIM_CALL.findall(body):
        if recv in bound:
            continue
        if recv in shims and not hasattr(shims[recv], meth):
            out.add((recv, meth))
    return sorted(out)


def _line_of(lines, needle) -> Optional[int]:
    """
    The 1-based line in *lines* holding *needle*, or None.

    Comment lines are skipped so a note does not point at the header
    describing it, and the first match wins: a name used three times is
    reported once, at the place someone would start reading.

    Args:
        lines: The emitted body, without the header.
        needle: A snippet to look for, or None.

    Returns:
        The line number, or None when there is nothing to find or the
        snippet does not appear -- some notes are about the verb as a
        whole and genuinely have no line.
    """
    if not needle:
        return None
    # Word boundaries at *both* ends.  Anchoring only the start made the
    # needle 'a' match inside 'args', so a note about an undefined `a`
    # pointed at `name = args` -- confidently, and at the wrong line.
    # The trailing boundary is skipped when the needle already ends in a
    # non-word character, as `call_function('read'` does, since \b after
    # a quote would never match.
    tail = r'\b' if needle[-1:].isalnum() or needle[-1:] == '_' else ''
    pattern = re.compile(r'\b' + re.escape(needle) + tail)
    for i, line in enumerate(lines, 1):
        if line.lstrip().startswith(MARK):
            continue
        if pattern.search(line):
            return i
    return None


def _will_not_parse(code: str) -> Optional[str]:
    """
    Why the translated code is not valid Python, if it is not.

    Args:
        code: Translated Python, ``# PORT:`` lines and all.

    Returns:
        The syntax error's message, or None when it parses.  Object
        literals are resolved first, since ``#1`` is this engine's
        spelling and not Python's; the body is wrapped in a function
        because a verb may legitimately use a bare ``return``.
    """
    body = '\n'.join(l for l in code.splitlines()
                      if not l.strip().startswith(MARK))
    if not body.strip():
        return None
    try:
        from .verbs import preprocess_objrefs
        body = preprocess_objrefs(body)
    except Exception:
        pass
    wrapped = 'def _v():\n' + '\n'.join('    ' + l for l in body.splitlines())
    try:
        # compile(), not ast.parse().  Some restrictions are enforced after
        # the parse tree is built and only compile() sees them -- a walrus
        # in a comprehension's iterable parses fine and will not compile,
        # which is exactly what the emitter was producing.  The check has
        # to be the same one the server will apply on load, or it is
        # promising something it did not test.
        compile(wrapped, '<verb>', 'exec')
    except SyntaxError as err:
        return err.msg
    return None


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
    # Resolve objrefs first.  `#300` is a comment to Python, so a body
    # containing one either loses the rest of its line or fails to parse
    # outright -- and this function returns {} on a SyntaxError, so the
    # loops inside simply went uncounted.  That is what made a correct
    # translation of Inferno's forked verbs report as having dropped
    # three for-loops it had translated perfectly well.
    try:
        # preprocess_objrefs, not preprocess_verb_code: the latter also
        # wraps the body in `def _verb_(): ...`, which adds a return of
        # its own and makes the counts describe the wrapper.
        from .verbs import preprocess_objrefs
        body = preprocess_objrefs(body)
    except Exception:
        pass
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
        # A forked body is a string here, so its loops are invisible to the
        # walk above.  Left uncounted, a verb that forked a loop was
        # reported as having dropped one -- an alarm about code that was
        # translated perfectly well, which is worse than no check at all.
        elif (isinstance(node, ast.Assign) and
                isinstance(node.value, ast.Constant) and
                isinstance(node.value.value, str) and
                any(isinstance(t, ast.Name) and t.id.startswith('_forked_')
                    for t in node.targets)):
            for k, v in structure_of_python(node.value.value).items():
                counts[k] = counts.get(k, 0) + v
    return counts


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def port(source: str, resolve=None, maps: bool = False) -> PortResult:
    """
    Translate MOO source to Python.

    Args:
        source: MOO verb code.
        resolve: Optional ``name -> bool`` answering whether ``$name``
            is defined on #0.  @port passes the live database's, so a
            reference to an object that really is there translates
            clean instead of being marked on suspicion.
        maps: Whether the source dialect has maps.  False for LambdaMOO
            1.8, which has none; True for ToastStunt, where a subscript
            may be a key lookup and cannot be shifted blindly.

    Returns:
        A :class:`PortResult`.  ``code`` is Python; ``notes`` lists what
        needs a human; ``marks`` counts the ``# PORT:`` lines left in.

    Raises:
        MooSyntaxError: The source is not MOO this can parse.  Nothing
            partial is returned -- a half-parsed verb would be worse than
            none.
    """
    p = Porter(source, resolve=resolve, maps=maps)
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
               f"probably a MOO builtin with no equivalent here", find=name)

    for recv, meth in _missing_shim_methods('\n'.join(lines)):
        p.marks += 1
        p.note(f'{recv}.{meth}() is not implemented; ${_SHIM_NAMES[recv]} '
               f'has this method in a real MOO and the port of it here '
               f'does not, so this line will fail when it runs',
               find=f'{recv}.{meth}')

    # Does the output actually parse?
    #
    # This check was missing, and its absence was worse than any single
    # bug it would have caught.  The two checks above -- undefined names
    # and dropped control flow -- both fail *open* on a SyntaxError,
    # returning nothing rather than complaining, so invalid Python sailed
    # through both and came out marked clean.  Across the two stock cores
    # that was 161 verbs claiming the translator "believes it handled
    # this completely" while not compiling at all.
    #
    # It is a one-line check that subsumes an open-ended class of bugs,
    # which is the argument for having it at the end of the pipeline
    # rather than trusting each emitter to be right.
    syntax_error = _will_not_parse('\n'.join(lines))
    if syntax_error:
        p.marks += 1
        p.note(f'the translation does not parse as Python ({syntax_error}); '
               f'this is a bug in the translator, not in your MOO')

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

    # Put a line number on every note we can place.  The numbering is of
    # the finished verb -- header included -- because that is the file a
    # person opens, and "line 34" has to mean line 34 of what they are
    # looking at.
    header_len = (len(p.notes) + 2) if p.notes else 0
    located = []
    for note, find in zip(p.notes, p.locators + [None] * len(p.notes)):
        n = _line_of(lines, find)
        located.append(f'line {n + header_len}: {note}' if n else note)

    header = []
    if p.notes:
        header = [f'{MARK} {len(p.notes)} thing(s) here need a human:']
        header += [f'{MARK}   - {n}' for n in located]
        header += ['']
    return PortResult('\n'.join(header + lines) + '\n', located, p.marks)
