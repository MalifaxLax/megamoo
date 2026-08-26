"""
MegaMOO Verb System -- Pure Python Scripting

This module implements verb definitions and execution using Python as the
scripting language. Verbs are Python functions with full access to the
Python standard library and all MegaMOO features.

Architecture Overview:

    Unlike classic LambdaMOO (which uses the MOO programming language),
    MegaMOO stores verbs as **raw Python code strings**.  When a verb is
    created or loaded from the database, its code is preprocessed
    (``#N`` object references and ``$name`` system-property references
    are rewritten) and compiled to a Python code object.

    At execution time the compiled code runs inside a carefully
    constructed namespace that provides the verb's context variables
    (``pobj``, ``this``, ``dobj``, ``iobj``, etc.) alongside a curated
    set of built-in helpers (``notify``, ``move``, ``create``, etc.).
    Because the code is plain Python, verb authors have access to the
    full standard library, native data structures, and normal control
    flow (``if``/``for``/``try``/``return``).

    To allow ``return`` inside verb code, the preprocessor wraps the
    user's code inside a ``def _verb_(): ...`` function body, then
    immediately calls it and captures the result.

Key Features:
    - Verbs are stored as Python code strings
    - Full Python syntax and features available
    - Access to all Python built-ins (len, dict, set, etc.)
    - Native Python types in properties (dict, list, set, etc.)
    - Simple execution with exec()
    - No compiler needed!

Key Classes:
    VerbDef:        Dataclass holding a verb's code, metadata, and compiled form.
    VerbContext:    Runtime context object exposing parsed-command data to verbs.
    VerbExecutor:   Orchestrates permission checks, namespace creation, and exec().
    VerbError / CompileError / ExecutionError / PermissionDenied:
                    Exception hierarchy for verb-related failures.

Key Functions:
    preprocess_objrefs:   Low-level ``#N`` / ``$name`` rewriter.
    preprocess_verb_code: Rewrite + function-wrap for verb code.
    create_verb:          Convenience factory for ``VerbDef``.

Copyright (c) 2026
License: MIT
"""

# ---------------------------------------------------------------------------
# Standard library and third-party imports
# ---------------------------------------------------------------------------

from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
import logging
import re
import sys
import traceback

from .permissions import PermissionChecker, parse_perms, Permission
from .tasks import Task, TaskContext, TaskState
from .objects import MOOObject

logger = logging.getLogger('megamoo.verbs')


# ===========================================================================
# CODE PREPROCESSING -- REGEX PATTERNS
# ===========================================================================
# The preprocessing step converts MOO-style shorthand in verb source code
# into valid Python before compilation:
#   - ``#N``    -> ``db.get_object(N)``   (object reference)
#   - ``$name`` -> ``db.get_object(0).name`` (system property on #0)
#
# The master regex (_MASTER_RE) matches string literals, comments, object
# references, and system properties in a single pass.  String literals and
# comments are captured so they can be returned *unchanged* -- only bare
# code tokens are rewritten.

# Simple patterns used inside f-string brace expressions where the
# master regex cannot be applied (f-string innards are processed
# character-by-character).
_OBJREF_RE = re.compile(r'#(\d+)')
_SYSPROP_RE = re.compile(r'\$([A-Za-z_]\w*)')

# $names that should resolve to Python namespace variables rather than
# being rewritten to ``db.get_object(0).name``.  For example, ``$su``
# is the string-utilities module imported directly into the verb namespace.
#
# ``$string_utils`` is an alias for the same object, so code ported from a
# MOO keeps the name it was written with. The only edit a port needs is
# the call syntax:
#
#     $string_utils:from_list(lst, ", ")    MOO
#     $string_utils.from_list(lst, ", ")    here
#
# There is deliberately no #60 object behind it. call_verb() takes an
# argument *string*, so a verb could not accept positional arguments the
# way the MOO original does; a method on su is both faster and closer to
# the source it replaces.
_PYTHON_CONSTANTS = {'su', 'string_utils'}

# Master regex: matches seven distinct token types in verb source code.
# Groups 1-4 capture string literals (returned unchanged).
# Group 5 captures comments (returned unchanged).
# Group 6 captures ``#N`` object references (rewritten).
# Group 7 captures ``$name`` system properties (rewritten).
_MASTER_RE = re.compile(
    r"('''[\s\S]*?''')"            # 1: triple single-quoted string
    r'|("""[\s\S]*?""")'           # 2: triple double-quoted string
    r"|('[^'\\]*(?:\\.[^'\\]*)*')" # 3: single-quoted string
    r'|("[^"\\]*(?:\\.[^"\\]*)*")' # 4: double-quoted string
    # 5: a comment.  Two shapes, because `#N` collides with Python's own
    # comment syntax and the collision is real: `#5 minute cooldown` at
    # column 0 is prose, and used to compile as `db.get_object(5) minute
    # cooldown` -- a SyntaxError pointing at a line that is visibly a
    # comment.  What follows the digits decides.  Punctuation, an
    # operator or end-of-expression means a reference (`#5.foo`, `f(#5)`,
    # `o == #5`); whitespace then a word means prose.  Python's word
    # operators are the exception -- `#5 and x`, `#5 in y` are code, not
    # commentary -- so they are excluded by name.
    r'|(\#(?!\d).*$'
    r'|\#\d+[ \t]+(?!(?:and|or|not|in|is|if|else|for)\b)[A-Za-z_][^\n]*$)'
    r'|(\#\d+)'                    # 6: object ref #N
    r'|(\$[A-Za-z_]\w*)',          # 7: system property $name
    re.MULTILINE
)


# ===========================================================================
# CODE PREPROCESSING -- REWRITE FUNCTIONS
# ===========================================================================


class UnsafeValue(ValueError):
    """A `@set` value that is not a literal.  Carries the offending node."""


def eval_value_literal(processed: str, db):
    """Evaluate a property value written by a player, without running it.

    `@set x.p = <value>` and `@adprop` used real ``eval()`` on the argument.
    They are gm3 commands, so that was arbitrary Python in the server's
    process for anyone who could set a description --

        @set me.description = __import__('socket').gethostname()

    -- which made the gm5 gate on `@program`, `@adverb` and `eval` worth
    nothing: the cheap command was the way in.

    What those commands actually need is a *literal*, possibly containing
    object references.  `preprocess_objrefs` has already rewritten `#5` to
    ``db.get_object(5)`` and `$item` to ``db.get_object(0).item``, so this
    walks the parse tree and evaluates exactly that grammar and nothing
    else: constants, lists, tuples, sets, dicts, a leading minus, those
    `get_object` calls, and attribute access on them.

    Anything else raises, including a bare name -- `@set` treats a failure
    on unprocessed input as "store it as a string", which is what makes
    ``@set x.title = Champion`` work.

    Args:
        processed: The argument, after `preprocess_objrefs`.
        db: The database, for resolving object references.

    Returns:
        The value.

    Raises:
        UnsafeValue: If the expression is not a literal of that grammar.
        SyntaxError: If it does not parse.
    """
    import ast

    def _fail(node):
        raise UnsafeValue('%s is not allowed in a value'
                          % type(node).__name__)

    def _is_get_object(node):
        return (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'get_object'
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == 'db'
                and len(node.args) == 1
                and not node.keywords
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, int))

    def _eval(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.List):
            return [_eval(e) for e in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(_eval(e) for e in node.elts)
        if isinstance(node, ast.Set):
            return {_eval(e) for e in node.elts}
        if isinstance(node, ast.Dict):
            return {_eval(k): _eval(v)
                    for k, v in zip(node.keys, node.values)}
        if isinstance(node, ast.UnaryOp) and isinstance(
                node.op, (ast.UAdd, ast.USub)):
            v = _eval(node.operand)
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                _fail(node)
            return v if isinstance(node.op, ast.UAdd) else -v
        if _is_get_object(node):
            return db.get_object(node.args[0].value)
        if isinstance(node, ast.Attribute):
            # `$name` and `#N.prop`, which preprocess_objrefs produces.
            # Underscored names are refused: `#1.__class__` is where every
            # Python escape starts, and no property a player sets is called
            # that.
            if node.attr.startswith('_'):
                raise UnsafeValue('%r is not a property name you can read '
                                  'here' % node.attr)
            return getattr(_eval(node.value), node.attr)
        _fail(node)

    return _eval(ast.parse(processed, mode='eval').body)


def preprocess_objrefs(code: str) -> str:
    """
    Rewrite MOO-style shorthand in source code into valid Python.

    Specifically:
    * ``#N`` object references become ``db.get_object(N)`` calls.
    * ``$name`` system property references become
      ``db.get_object(0).name`` (i.e. a property on the system object).

    String literals, f-string text, and comments are left untouched.
    F-string *brace expressions* (``{...}``) **are** processed so that
    ``f"Hello {#5.name}"`` works as expected.

    This is the low-level pass shared by both verb compilation and
    the ``eval``/``exec`` helpers.

    Args:
        code (str): Raw source code potentially containing ``#N`` and
            ``$name`` tokens.

    Returns:
        str: The rewritten source code with all references expanded.

    Examples::

        "obj = #5"              -> "obj = db.get_object(5)"
        "s = '#5 is cool'"      -> "s = '#5 is cool'"       (unchanged)
        "f'Object {#5.name}'"   -> "f'Object {db.get_object(5).name}'"
        "x = #1  # ref #2"     -> "x = db.get_object(1)  # ref #2"
        "$eu.do_thing()"        -> "eu.do_thing()"
        "s = '$literal'"        -> "s = '$literal'"          (unchanged)

    Notes:
        The function uses a single-pass regex (``_MASTER_RE``) that
        matches all seven token types simultaneously.  Because string
        literals and comments are matched *before* ``#N`` and ``$name``,
        they are returned unchanged by the replacement callback.
    """

    def _replace_objref(m):
        """Simple ``#N`` -> ``db.get_object(N)`` for use inside f-strings."""
        return f'db.get_object({m.group(1)})'

    def _replace_sysprop(m):
        """Simple ``$name`` -> ``db.get_object(0).name`` for use inside f-strings."""
        name = m.group(1)
        if name in _PYTHON_CONSTANTS:
            return name
        return f'db.get_object(0).{name}'

    def _process_fstring(s):
        """
        Process the interior of an f-string literal.

        Walk character-by-character tracking brace depth.  Text outside
        ``{...}`` is copied verbatim; text *inside* braces is run
        through the simple ``_OBJREF_RE`` / ``_SYSPROP_RE`` patterns.

        Escaped braces (``{{`` / ``}}``) are skipped so they are not
        mistaken for expression delimiters.

        Args:
            s (str): The full f-string literal including its quotes.

        Returns:
            str: The f-string with expressions rewritten.
        """
        result = []
        i = 0
        depth = 0
        buf_start = 0
        while i < len(s):
            ch = s[i]
            # Skip escaped braces ({{ and }})
            if ch == '{' and i + 1 < len(s) and s[i + 1] == '{':
                i += 2
                continue
            if ch == '}' and i + 1 < len(s) and s[i + 1] == '}':
                i += 2
                continue
            # Entering a brace expression
            if ch == '{' and depth == 0:
                result.append(s[buf_start:i + 1])  # Include the '{'
                depth = 1
                buf_start = i + 1
                i += 1
                continue
            # Inside a brace expression -- track nested braces
            if depth > 0:
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        # End of top-level expression -- rewrite it
                        expr = s[buf_start:i]
                        expr = _OBJREF_RE.sub(_replace_objref, expr)
                        expr = _SYSPROP_RE.sub(_replace_sysprop, expr)
                        result.append(expr)
                        result.append('}')
                        buf_start = i + 1
            i += 1
        # Append any trailing text (typically the closing quote)
        result.append(s[buf_start:])
        return ''.join(result)

    def _replace(m):
        """Master replacement callback dispatched by ``_MASTER_RE``."""
        # Group 6: bare #N object reference in code
        if m.group(6) is not None:
            objnum = m.group(6)[1:]  # Strip the '#'
            return f'db.get_object({objnum})'
        # Group 7: bare $name system property reference in code
        if m.group(7) is not None:
            prop_name = m.group(7)[1:]  # Strip the '$'
            if prop_name in _PYTHON_CONSTANTS:
                return prop_name
            return f'db.get_object(0).{prop_name}'
        # Groups 1-4: string literals -- check if preceded by 'f'/'F'
        for g in (1, 2, 3, 4):
            s = m.group(g)
            if s is not None:
                start = m.start(g)
                # If the string is an f-string, process brace expressions
                if start > 0 and code[start - 1] in 'fF':
                    return _process_fstring(s)
                # Plain string -- return unchanged
                return s
        # Group 5 (comment) or anything else -- return unchanged
        return m.group(0)

    return _MASTER_RE.sub(_replace, code)


def preprocess_verb_code(code: str) -> str:
    """
    Preprocess verb code: rewrite references and wrap in a function.

    This is the high-level preprocessing entry point used when compiling
    a verb.  It performs two steps:

    1. **Reference rewriting** -- calls ``preprocess_objrefs()`` to
       convert ``#N`` and ``$name`` tokens into valid Python.
    2. **Function wrapping** -- wraps the entire code body inside a
       ``def _verb_(): ...`` function and immediately calls it, so that
       ``return`` statements in verb code work naturally.

    The generated wrapper looks like::

        def _verb_():
            <original code, indented>
        result = _verb_()

    The inner function inherits the calling namespace's globals (``pobj``,
    ``this``, ``db``, etc.) and benefits from CPython's ``LOAD_FAST``
    optimisation for any variables the verb assigns locally.

    Args:
        code (str): Raw verb code string as written by the builder.

    Returns:
        str: Preprocessed, function-wrapped Python code ready for
        ``compile()`` and ``exec()``.

    Notes:
        Empty lines are preserved (but not indented) to keep error
        tracebacks aligned with the original source line numbers as
        closely as possible.
    """
    processed = preprocess_objrefs(code)

    # Indent each non-empty line one level and wrap in def/call.
    # Empty lines are left blank to preserve line-number alignment.
    lines = processed.split('\n')
    indented = '\n'.join('    ' + line if line.strip() else '' for line in lines)

    # Honour both ways a verb can answer its caller:
    #
    #   return X        -- returns immediately, as Python does
    #   result = X      -- the documented MOO-style idiom
    #
    # The second needs help. Verb code runs inside a function, so a bare
    # ``result = X`` binds a local that is discarded when the function
    # returns None. Verbs written that way -- do_wait among them -- were
    # silently answering None to every caller, which turned guards like
    # ``if call_verb(pobj, 'do_wait'):`` into no-ops that still printed
    # their message, so they looked as though they worked.
    #
    # The trailing lookup runs only when control falls off the end, so an
    # explicit ``return`` still wins. It is appended rather than paired
    # with a prologue assignment so verb line numbers stay aligned with
    # tracebacks.
    tail = "    return locals().get('result')"
    return f'def _verb_():\n{indented}\n{tail}\nresult = _verb_()'


# ===========================================================================
# EXCEPTION HIERARCHY
# ===========================================================================


class VerbError(Exception):
    """
    Base class for all verb-related errors.

    Catch this to handle any verb failure generically, or catch the
    specific subclasses below for finer control.
    """
    pass


class CompileError(VerbError):
    """
    Raised when verb source code fails to compile.

    Typically wraps a ``SyntaxError`` from Python's ``compile()``
    built-in, but may also indicate other preprocessing failures.
    """
    pass


class ExecutionError(VerbError):
    """
    Raised when a compiled verb raises an exception at runtime.

    The original exception is chained (``raise ... from e``) so the
    full traceback is available for debugging.
    """
    pass


class PermissionDenied(VerbError):
    """
    Raised when a player lacks permission to execute a verb.

    Permission checks are performed by ``PermissionChecker`` based on
    the verb's ``perms`` string and the player's flags/ownership.
    """
    pass


# ===========================================================================
# VERB DEFINITION
# ===========================================================================


@dataclass
class VerbDef:
    """
    Verb definition -- a named piece of Python code attached to a MOO object.

    Each verb has one or more *names* (aliases) and a body of Python source
    code.  The *parent_type* field is a dotted path to a class in
    :mod:`moo.verb_types` (e.g. ``'moo.verb_types.MasterVerb'``).
    When the verb executes, an instance of that class is created,
    its ``parse()`` method splits the argument string, and the
    resulting attributes (``dobj``, ``prep``, ``iobj``, etc.) are
    injected into the code string's namespace.

    Attributes:
        names (List[str]): Verb names / aliases.  The first name is
            considered the "primary" name and is used in log messages
            and the compilation source tag.
        code (str): Python source code as a string.  This is the raw
            code as entered by the builder; preprocessing and function-
            wrapping happen at compile time.
        owner (int): Object number of the player who owns (wrote) this
            verb.  Used for permission checks.
        perms (str): Permission string controlling who can execute,
            read, or write the verb:
            ``'r'`` -- verb code is readable by non-owners.
            ``'w'`` -- verb code is writable by the owner.
            ``'x'`` -- verb is executable.
            ``'d'`` -- verb can be called with debug tracing.
        parent_type (str): Dotted import path to the verb's parent
            class in ``moo.verb_types``.  The parent class controls
            how command arguments are parsed (direct object, preposition,
            indirect object, etc.).
        min_lengths (Dict[str, int]): Optional minimum prefix lengths
            for abbreviation matching.  ``{'examine': 3}`` means 'exa',
            'exam', etc. all match.  Names without an entry require
            an exact match.
        hidden (bool): If ``True``, the verb is excluded from verb
            listings and ``find_verb`` results.  Used for internal/
            system verbs that should not appear in ``@verbs``.
        auth (int): Object number required as the calling player for
            this verb to execute.  ``0`` means no restriction.
        compiled_code: The compiled Python code object (output of
            ``compile()``).  ``None`` until ``compile()`` is called;
            automatically populated by ``__post_init__``.

    Notes:
        VerbDef instances are stored in ``MOOObject.verbs`` and
        serialised via ``to_dict()`` / ``from_dict()``.  The
        ``compiled_code`` field is transient and not persisted.
    """
    names: List[str]
    code: str
    owner: int
    perms: str = 'rx'
    parent_type: str = 'moo.verb_types.MasterVerb'
    min_lengths: Dict[str, int] = field(default_factory=dict)
    hidden: bool = False
    auth: int = 0
    compiled_code: Any = None
    
    def __post_init__(self):
        """
        Eagerly compile verb code on dataclass construction.

        Compilation is best-effort: if the code has syntax errors, a
        warning is logged but no exception is raised.  This allows
        objects with broken verbs to still be loaded from the database.
        The verb will raise ``CompileError`` later if someone actually
        tries to execute it.
        """
        if self.code and not self.compiled_code:
            try:
                self.compile()
            except Exception as e:
                logger.error(f"Failed to compile verb {self.names}: {e}")
                
    def compile(self):
        """
        Preprocess and compile the verb's Python source code.

        The compilation pipeline is:
        1. ``preprocess_verb_code()`` rewrites ``#N`` / ``$name`` tokens
           and wraps the code in a ``def _verb_(): ...`` function body.
        2. Python's ``compile()`` built-in produces a code object.

        The resulting code object is stored in ``self.compiled_code`` and
        reused on every execution until the verb's source is changed.

        Raises:
            CompileError: If the code contains a ``SyntaxError`` or any
                other error during preprocessing / compilation.
        """
        try:
            # Step 1: rewrite MOO references and wrap in function
            processed_code = preprocess_verb_code(self.code)

            # Step 2: compile to a Python code object.
            # The filename tag "<verb NAME>" appears in tracebacks.
            self.compiled_code = compile(
                processed_code,
                f"<verb {self.names[0]}>",
                'exec'
            )
            logger.debug(f"Compiled verb: {self.names[0]}")
        except SyntaxError as e:
            raise CompileError(f"Syntax error in verb code: {e}")
        except Exception as e:
            raise CompileError(f"Failed to compile verb: {e}")
            
    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize this verb definition to a plain dictionary.

        Only non-default optional fields (``min_lengths``, ``hidden``,
        ``auth``) are included to keep the stored representation compact.
        The ``compiled_code`` field is intentionally omitted because it
        is transient and rebuilt on load.

        Returns:
            dict: A JSON-compatible dictionary suitable for database
            storage.
        """
        d = {
            'names': self.names,
            'code': self.code,
            'owner': self.owner,
            'perms': self.perms,
            'parent_type': self.parent_type,
        }
        # Only include optional fields when they have non-default values
        if self.min_lengths:
            d['min_lengths'] = self.min_lengths
        if self.hidden:
            d['hidden'] = True
        if self.auth:
            d['auth'] = self.auth
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VerbDef':
        """
        Reconstruct a VerbDef from a serialised dictionary.

        Missing keys are filled with sensible defaults so that older
        database formats (which may lack ``min_lengths``, ``hidden``,
        or ``auth``) load without errors.

        The verb's code is compiled eagerly by ``__post_init__``; if
        compilation fails, a warning is logged but the VerbDef is
        still returned so the object can be loaded.

        Args:
            data (dict): Verb data dictionary as produced by ``to_dict()``.

        Returns:
            VerbDef: A fully-populated verb definition.
        """
        return cls(
            names=data.get('names', []),
            code=data.get('code', ''),
            owner=data.get('owner', 0),
            perms=data.get('perms', 'rx'),
            parent_type=data.get('parent_type', 'moo.verb_types.MasterVerb'),
            min_lengths=data.get('min_lengths', {}),
            hidden=data.get('hidden', False),
            auth=data.get('auth', 0),
        )

    # ------------------------------------------------------------------
    # Name matching
    # ------------------------------------------------------------------
    # MOO verbs support two kinds of name matching:
    #   1. Exact match:  input == verb name
    #   2. Prefix match: input is a prefix of verb name, and the
    #      prefix is at least ``min_lengths[name]`` characters long.
    #
    # ``matchable_names()`` pre-expands all valid prefixes so they
    # can be inserted into the inheritance cache for O(1) lookup.
    # ``matches()`` performs the check at verb-call time.

    def matchable_names(self) -> List[str]:
        """
        Return every string that should match this verb.

        For names with a ``min_lengths`` entry, this includes every
        prefix from ``min_lengths[name]`` characters up to the full
        name.  For names without an entry, only the exact name is
        returned.

        Returns:
            List[str]: All matchable strings for this verb.

        Example::

            VerbDef(names=['examine', 'x'], min_lengths={'examine': 3})
            # -> ['exa', 'exam', 'exami', 'examin', 'examine', 'x']
        """
        result = []
        for name in self.names:
            mn = self.min_lengths.get(name)
            if mn is not None and mn < len(name):
                # Generate every valid prefix from min_length to full name
                for i in range(mn, len(name) + 1):
                    result.append(name[:i])
            else:
                result.append(name)
        return result

    def matches(self, input_name: str) -> bool:
        """
        Test whether *input_name* matches any name or abbreviation.

        Args:
            input_name (str): The player's typed verb name.

        Returns:
            bool: ``True`` if this verb should handle *input_name*.

        Notes:
            This method is used in the fast-path local verb check
            (before the inheritance cache is consulted).
        """
        for name in self.names:
            if input_name == name:
                return True
            mn = self.min_lengths.get(name)
            # Check if input is a valid prefix (at least min_length chars,
            # shorter than the full name, and the full name starts with it)
            if mn is not None and mn <= len(input_name) < len(name):
                if name.startswith(input_name):
                    return True
        return False


# ===========================================================================
# VERB EXECUTION CONTEXT
# ===========================================================================


class VerbContext:
    """
    Runtime context object providing parsed-command data to executing verbs.

    When a verb is about to run, a ``VerbContext`` is constructed from the
    current ``Task`` and (optionally) a parsed command result.  The context
    resolves all object numbers to live ``MOOObject`` instances so that
    verb code can access them directly::

        # Inside verb code, these are available as globals:
        player.msg(f"Hello from {this.name}!")
        if dobj:
            notify(player, f"You pick up {dobj.name}.")

    Attributes:
        database:  The active database instance (for ad-hoc lookups).
        task (Task):  The task object governing this execution (tick
            counts, timeouts, etc.).
        player (MOOObject):  The player who typed the command.
        this (MOOObject):  The object the verb is defined on.
        caller (MOOObject or None):  The calling object when invoked
            via ``call_verb()``; ``None`` for top-level commands.
        location (MOOObject or None):  The player's current location.
        verb (str):  The verb name as typed by the player.
        switches (List[str]):  Any ``/switch`` flags on the command
            (e.g. ``look/brief`` -> ``['brief']``).
        args (list):  The argument list (split words).
        argstr (str):  The full argument string (unsplit).
        dobjstr (str):  The direct-object string as typed.
        prep (str):  The preposition string (e.g. "in", "on", "with").
        iobjstr (str):  The indirect-object string as typed.
        dobj (MOOObject or None):  Resolved direct object.
        iobj (MOOObject or None):  Resolved indirect object.
    """

    def __init__(self, database, task: Task, parse_result=None):
        """
        Build a verb context from a task and optional parse result.

        Args:
            database: Database instance for resolving object numbers.
            task (Task): The current execution task.
            parse_result: A parsed command object (with ``.verb``,
                ``.dobj``, ``.iobj``, etc.).  If ``None``, context
                values are taken directly from the task's
                ``TaskContext``.

        Notes:
            Object resolution (``database.get_object()``) is wrapped
            in try/except so that recycled or invalid object numbers
            result in ``None`` rather than crashing the verb.
        """
        self.database = database
        self.task = task

        # --- Resolve core objects from the task context ---
        self.player = database.get_object(task.context.player)
        self.this = database.get_object(task.context.this)
        self.caller = None
        if task.context.caller > 0:
            try:
                self.caller = database.get_object(task.context.caller)
            except Exception:
                pass  # Caller may have been recycled

        # Player's current location (may be None if player is nowhere)
        self.location = self.player.location

        # --- Populate command parsing data ---
        if parse_result:
            # A full parse result is available (normal command dispatch)
            self.verb = parse_result.verb
            self.switches = parse_result.switches or []
            self.args = parse_result.args
            self.argstr = parse_result.argstr
            self.dobjstr = parse_result.dobjstr
            self.prep = parse_result.prep
            self.iobjstr = parse_result.iobjstr

            # Resolve direct and indirect objects to live MOOObjects
            self.dobj = None
            if parse_result.dobj > 0:
                try:
                    self.dobj = database.get_object(parse_result.dobj)
                except Exception:
                    pass

            self.iobj = None
            if parse_result.iobj > 0:
                try:
                    self.iobj = database.get_object(parse_result.iobj)
                except Exception:
                    pass
        else:
            # No parse result -- fall back to raw task context fields
            # (used for programmatic verb calls via call_verb)
            self.verb = task.context.verb
            self.switches = []
            self.args = task.context.args
            self.argstr = task.context.argstr
            self.dobjstr = task.context.dobjstr
            self.prep = task.context.prepstr
            self.iobjstr = task.context.iobjstr
            self.dobj = None
            self.iobj = None


# ===========================================================================
# VERB EXECUTOR
# ===========================================================================


class VerbExecutor:
    """
    Orchestrates permission checks, namespace creation, and execution.

    This is the central class responsible for running verb code.  The
    execution pipeline is:

    1. **Permission check** -- verify the player has 'x' permission on
       the verb (or is a wizard).
    2. **Context creation** -- build a ``VerbContext`` that resolves all
       relevant object numbers to live ``MOOObject`` instances.
    3. **Namespace creation** -- delegate to
       ``verb_namespace.build_verb_namespace()`` to construct the dict
       of globals the verb code will see (``pobj``, ``this``, ``db``,
       built-in helpers, etc.).
    4. **Execution** -- ``exec()`` the compiled code object inside the
       namespace.
    5. **Result capture** -- read ``namespace['result']``, which was
       set by the ``result = _verb_()`` call in the wrapper function.
    6. **Error handling** -- log errors, notify the player, and wrap
       the original exception in ``ExecutionError``.

    Attributes:
        database: The database instance used for object lookups.
        permission_checker (PermissionChecker): Evaluates verb perms
            against the acting player's flags and ownership.
    """

    def __init__(self, database):
        """
        Initialize the verb executor.

        Args:
            database: Database instance providing ``get_object()`` and
                object persistence.
        """
        self.database = database
        self.permission_checker = PermissionChecker(database)
        
    def execute(self, verb_def: VerbDef, task: Task, parse_result=None) -> Any:
        """
        Execute a verb definition within a task.

        This is the main entry point for verb execution.  It performs
        permission checks, builds the execution namespace, runs the
        compiled code, and captures the return value.

        Args:
            verb_def (VerbDef): The verb definition to execute.
            task (Task): The current task (provides player, tick budget,
                and context data).
            parse_result: An optional parsed command result providing
                dobj/prep/iobj etc.  If ``None``, raw task context
                fields are used.

        Returns:
            The return value from the verb code (whatever the verb's
            ``return`` statement yields), or ``None`` if the verb does
            not explicitly return.

        Raises:
            PermissionDenied: If the player lacks execute permission
                on this verb.
            ExecutionError: If the verb raises any exception at runtime.
                The original exception is chained for debugging.
        """
        # --- Permission check ---
        player_obj = self.database.get_object(task.context.player)
        verb_obj = self.database.get_object(task.context.this)

        if not self.permission_checker.can_execute_verb(player_obj, verb_obj, verb_def):
            raise PermissionDenied(f"You cannot execute verb '{verb_def.names[0]}'")

        # --- Build context and namespace ---
        context = VerbContext(self.database, task, parse_result)
        namespace = self._create_namespace(context, verb_def)

        # --- Execute ---
        from .verb_namespace import verb_body_vetoed, run_at_post_cmd
        try:
            # Lazy compilation: compile now if not already done
            if not verb_def.compiled_code:
                verb_def.compile()

            # at_pre_cmd() already ran during namespace construction; it
            # may have asked for the body to be skipped.
            if verb_body_vetoed(namespace):
                result = None
            else:
                # Run the compiled code inside the prepared namespace.
                # The wrapper function ``_verb_()`` runs the user's code and
                # stores its return value in ``namespace['result']``.
                exec(verb_def.compiled_code, namespace)

                # Retrieve the verb's return value (set by ``result = _verb_()``)
                result = namespace.get('result', None)

            run_at_post_cmd(namespace, result)

            # Charge ticks against the task's budget (simplified: 100 per verb)
            task.tick(100)

            return result

        except Exception as e:
            run_at_post_cmd(namespace, error=e)
            # --- Error handling ---
            logger.error(f"Error executing verb {verb_def.names[0]}: {e}")
            logger.error(traceback.format_exc())

            # Best-effort: show the error to the player in-game
            try:
                from .builtins import notify
                notify(context.player, f"Error in {verb_def.names[0]}: {str(e)}")
            except Exception:
                pass

            # Re-raise wrapped so callers can catch ExecutionError
            raise ExecutionError(f"Verb error: {e}") from e
            
    def _create_namespace(self, context: VerbContext, verb_def: VerbDef) -> Dict[str, Any]:
        """
        Build the globals dict that verb code executes inside.

        Delegates to :func:`verb_namespace.build_verb_namespace`, which
        is responsible for:
        - Injecting context variables (``pobj``, ``this``, ``dobj``, etc.)
        - Instantiating the verb's parent class and running its ``parse()``
        - Importing built-in helper functions (``notify``, ``move``, etc.)
        - Providing safe access to Python built-ins

        Args:
            context (VerbContext): The populated context for this execution.
            verb_def (VerbDef): The verb being executed (needed for
                parent-type resolution).

        Returns:
            Dict[str, Any]: A namespace dict ready to be passed to ``exec()``.
        """
        from .verb_namespace import build_verb_namespace

        return build_verb_namespace(
            pobj=context.player,
            this=context.this,
            db=self.database,
            verb_name=context.verb,
            args=context.argstr.strip() if context.argstr else '',
            argstr=context.argstr or '',
            location=context.location,
            caller=context.caller,
            context=context,
            verb_def=verb_def,
            parse_result=context,
        )


# ===========================================================================
# CONVENIENCE FACTORY
# ===========================================================================


def create_verb(names: List[str], code: str, owner: int,
                perms: str = 'rx',
                parent_type: str = 'moo.verb_types.MasterVerb',
                **kwargs) -> VerbDef:
    """
    Convenience factory for creating a new ``VerbDef``.

    This is a thin wrapper around the ``VerbDef`` constructor that
    provides sensible defaults and passes through any extra keyword
    arguments (``min_lengths``, ``hidden``, ``auth``, etc.).

    Args:
        names (List[str]): Verb names / aliases.
        code (str): Python source code for the verb body.
        owner (int): Object number of the verb's owner.
        perms (str): Permission string (default ``'rx'`` = readable
            and executable).
        parent_type (str): Dotted path to the parent verb class
            (default ``'moo.verb_types.MasterVerb'``).
        **kwargs: Additional keyword arguments forwarded directly to
            the ``VerbDef`` constructor (e.g. ``min_lengths``,
            ``hidden``, ``auth``).

    Returns:
        VerbDef: A newly constructed (and eagerly compiled) verb
        definition.
    """
    return VerbDef(
        names=names,
        code=code,
        owner=owner,
        perms=perms,
        parent_type=parent_type,
        **kwargs
    )
