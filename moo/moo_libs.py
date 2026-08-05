"""
Ports of LambdaMOO's utility objects, for code brought across by @port.

A MOO core leans on a handful of utility objects -- ``$string_utils``,
``$list_utils``, ``$command_utils`` and friends -- the way a Python program
leans on the standard library.  They are not part of the MOO *language*, so
no translator can produce them; ported code simply calls into a library
that is not there.  In JHCore that accounts for well over a thousand calls,
which was the single largest reason a translated verb still needed a human.

The usage is far more concentrated than the method counts suggest.
``$perm_utils`` is four methods.  Five methods cover 85% of
``$object_utils``; four cover 80% of ``$command_utils``.  So this is not a
reimplementation of a core -- it is the short head of each object, measured
against JHCore and written from JHCore's own definitions.

Indexing
--------

**These are 1-based, deliberately.**  ``assoc(t, lst, 2)`` means the second
element in MOO's counting, and @port does not shift arguments -- only
subscripts -- so a shim that quietly counted from zero would put every
ported call off by one.  That is the exact failure this whole exercise
keeps trying to avoid, so the compatibility layer stays faithful to MOO
even though it reads oddly from Python.

Each function's docstring quotes the JHCore original it was written from.
"""

from typing import Any, List, Optional

__all__ = ['lu', 'cu', 'cdu', 'ListUtils', 'CommandUtils', 'CodeUtils']

_MISSING = object()


def _player():
    """The acting player, from the verb context, or None outside one."""
    try:
        from .verb_context import verb_ctx
        ctx = verb_ctx.get()
        return ctx[0] if ctx else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# $list_utils
# ---------------------------------------------------------------------------

class ListUtils:
    """
    LambdaMOO's ``$list_utils`` (#49 in JHCore).

    All indices are 1-based, matching MOO.  See the module docstring.
    """

    @staticmethod
    def assoc(target: Any, lst: List, indx: int = 1):
        """
        First element of *lst* whose *indx*-th element is *target*.

        JHCore: "assoc(target,list[,index]) returns the first element of
        `list' whose own index-th element is target.  Index defaults to 1.
        returns {} if no such element is found".
        """
        for item in lst or []:
            if isinstance(item, (list, tuple)) and len(item) >= indx:
                if item[indx - 1] == target:
                    return item
        return []

    @staticmethod
    def iassoc(target: Any, lst: List, indx: int = 1) -> int:
        """
        Position of that element, 1-based, or 0 when absent.

        JHCore: "returns the index of the first element ... returns 0 if no
        such element is found."  Zero rather than -1, because ported code
        tests it for truth.
        """
        for i, item in enumerate(lst or [], start=1):
            if isinstance(item, (list, tuple)) and len(item) >= indx:
                if item[indx - 1] == target:
                    return i
        return 0

    @staticmethod
    def slice(alist: List, index: Any = 1) -> List:
        """
        The *index*-th element of each element of *alist*.

        JHCore: ``slice({{"z",1},{"y",2},{"x",5}},2) => {1,2,5}``.  *index*
        may also be a list, which reorders: ``slice({{"z",1,3}},{2,1})``
        gives ``{{1,"z"}}``.
        """
        out = []
        for elt in alist or []:
            if isinstance(index, (list, tuple)):
                out.append([elt[i - 1] for i in index])
            else:
                out.append(elt[index - 1])
        return out

    @staticmethod
    def map_arg(*args) -> List:
        """
        Call a verb on each element, passing it as an argument.

        JHCore's map_arg takes either ``(obj, verb, list, ...)`` or
        ``(verb, list)``.  Only the object form is meaningful here, since a
        bare verb name has nothing to run on.
        """
        from .builtins import call_verb
        if len(args) >= 3 and hasattr(args[0], 'objnum'):
            obj, verb, lst = args[0], args[1], args[2]
            extra = args[3:]
            return [call_verb(obj, verb, item, *extra) for item in lst or []]
        return list(args[-1] or []) if args else []

    @staticmethod
    def map_verb(obj, verb: str, lst: List) -> List:
        """Call *verb* on *obj* once per element of *lst*."""
        from .builtins import call_verb
        return [call_verb(obj, verb, item) for item in lst or []]

    @staticmethod
    def map_prop(lst: List, prop: str) -> List:
        """The named property of each object in *lst*."""
        return [getattr(o, prop, None) for o in lst or []]

    @staticmethod
    def remove_duplicates(lst: List) -> List:
        """Unique elements, first occurrence order kept."""
        out = []
        for item in lst or []:
            if item not in out:
                out.append(item)
        return out

    @staticmethod
    def reverse(lst: List) -> List:
        return list(reversed(lst or []))

    @staticmethod
    def sort(lst: List, keys: Optional[List] = None) -> List:
        """
        Sort *lst*, optionally by a parallel list of keys.

        JHCore sorts *lst* by *keys* when given, so the two travel together.
        """
        if keys:
            paired = sorted(zip(keys, lst or []), key=lambda p: p[0])
            return [v for _, v in paired]
        return sorted(lst or [])

    @staticmethod
    def find_insert(lst: List, target: Any) -> int:
        """
        Where *target* belongs in a sorted *lst*, 1-based.

        JHCore returns the index of the first element greater than target,
        which is where it would be inserted.
        """
        for i, item in enumerate(lst or [], start=1):
            if item > target:
                return i
        return len(lst or []) + 1

    @staticmethod
    def make(n: int, value: Any = 0) -> List:
        """A list of *n* copies of *value*."""
        return [value] * max(0, int(n))

    @staticmethod
    def check_type(lst: List, types) -> bool:
        """Whether every element of *lst* is one of *types*."""
        want = types if isinstance(types, (list, tuple)) else [types]
        return all(any(isinstance(x, t) for t in want) for x in lst or [])

    @staticmethod
    def setadd(lst: List, item: Any) -> List:
        """Add *item* unless present, as MOO's setadd builtin does."""
        lst = list(lst or [])
        return lst if item in lst else lst + [item]

    @staticmethod
    def setremove(lst: List, item: Any) -> List:
        """Remove the first *item* if present."""
        out = list(lst or [])
        if item in out:
            out.remove(item)
        return out

    @staticmethod
    def compress(lst: List) -> List:
        """Collapse runs of equal adjacent elements."""
        out = []
        for item in lst or []:
            if not out or out[-1] != item:
                out.append(item)
        return out


# ---------------------------------------------------------------------------
# $command_utils
# ---------------------------------------------------------------------------

class CommandUtils:
    """
    LambdaMOO's ``$command_utils``.

    Four methods are 80% of its use in JHCore, and they are the ones that
    talk to the player, so they route through ``msg`` -- overridable per
    object -- rather than the raw notify builtin.
    """

    @staticmethod
    def suspend_if_needed(seconds: float = 0, *_):
        """
        Yield if the task has been running a while.

        In MOO this checks the remaining tick budget and suspends before
        the server kills the task.  There are no ticks here; what matters
        is the same though -- a long loop should let the world move -- so
        it yields unconditionally, which suspend(0) does cheaply.
        """
        try:
            from .verb_baton import suspend, holder
            if holder():
                suspend(seconds or 0)
        except Exception:
            pass

    @staticmethod
    def object_match_failed(match_result, name: str, who=None) -> bool:
        """
        Explain a failed object match, the way MOO's core does.

        Returns True when the match *did* fail, so ported code keeps
        reading as ``if ($command_utils:object_match_failed(o, name)) return;``
        """
        who = who or _player()
        target = match_result
        failed = True
        if target is None or target == -1:
            msg = f'I see no "{name}" here.'
        elif target == -2:
            msg = f'I don\'t know which "{name}" you mean.'
        elif target == -3:
            msg = f'There are several objects named "{name}" here.'
        else:
            failed = False
            msg = ''
        if failed and who is not None and msg:
            who.msg(msg)
        return failed

    @staticmethod
    def player_match_failed(match_result, name: str, who=None) -> bool:
        """As object_match_failed, but phrased for people."""
        who = who or _player()
        if match_result is None or match_result in (-1, -2, -3):
            if who is not None:
                who.msg(f'I don\'t know anyone named "{name}".')
            return True
        return False

    @staticmethod
    def player_match_result(results, names, who=None) -> bool:
        """Report on a batch of player matches; True if any failed."""
        bad = False
        for result, name in zip(results or [], names or []):
            if CommandUtils.player_match_failed(result, name, who):
                bad = True
        return bad

    @staticmethod
    def yes_or_no(prompt: str = '', who=None) -> bool:
        """
        Ask a yes/no question.

        MOO blocks on read() here.  A verb cannot block for input without
        stopping the world, so this cannot be answered inline -- an
        interactive session is the way, and @port marks the call rather
        than pretending otherwise.
        """
        raise NotImplementedError(
            "yes_or_no() needs to block for input; use an interactive "
            "session (see @program's editor) rather than calling this")


# ---------------------------------------------------------------------------
# $code_utils
# ---------------------------------------------------------------------------

class CodeUtils:
    """
    LambdaMOO's ``$code_utils`` -- the short head only.

    This object has a 54-method long tail in JHCore and the top five are
    barely a third of its use, so only the parsing helpers that ported code
    actually reaches for are here.  Anything else stays marked, which is
    the honest outcome.
    """

    @staticmethod
    def parse_verbref(spec: str):
        """
        Split ``object:verb`` into its two halves.

        Returns ``[object, verb]``, or ``[]`` when there is no colon --
        MOO returns the empty list for "not a verb reference".
        """
        if not isinstance(spec, str) or ':' not in spec:
            return []
        obj, _, verb = spec.rpartition(':')
        return [obj.strip(), verb.strip()] if obj.strip() else []

    @staticmethod
    def parse_propref(spec: str):
        """Split ``object.property``.  ``[]`` when there is no dot."""
        if not isinstance(spec, str) or '.' not in spec:
            return []
        obj, _, prop = spec.rpartition('.')
        return [obj.strip(), prop.strip()] if obj.strip() else []

    @staticmethod
    def tonum(value) -> int:
        """MOO's tonum: a number, or 0 when it is not one."""
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def toobj(value):
        """Resolve to an object, or None."""
        from .builtins import _database
        try:
            if hasattr(value, 'objnum'):
                return value
            text = str(value).lstrip('#')
            return _database.get_object(int(text))
        except Exception:
            return None

    @staticmethod
    def error_name(err) -> str:
        """The name of an error value, e.g. ``E_PERM``."""
        return getattr(err, 'code', None) or str(err)

    @staticmethod
    def verb_or_property(obj, name: str) -> str:
        """Whether *name* on *obj* is a verb, a property, or neither."""
        try:
            for v in obj.verbs or []:
                if name in (v.names or []):
                    return 'verb'
        except Exception:
            pass
        return 'property' if getattr(obj, name, None) is not None else ''

    #: Prepositions, in LambdaMOO's own order.
    PREPS = [
        'with/using', 'at/to', 'in front of', 'in/inside/into',
        'on top of/on/onto/upon', 'out of/from inside/from', 'over',
        'through', 'under/underneath/beneath', 'behind', 'beside',
        'for/about', 'is', 'as', 'off/off of',
    ]

    # -- verb introspection ---------------------------------------------

    @staticmethod
    def find_verb_named(obj, name: str, start: int = 1) -> int:
        """
        Position of the first verb on *obj* called *name*, 1-based.

        LambdaCore: "returns the *number* of the first verb on object
        matching the given name ... 0 is returned if no verb is found.
        This routine does not find inherited verbs."  That last clause is
        the point: only the object's own verbs are searched.
        """
        try:
            own = list(obj.verbs or [])
        except Exception:
            return 0
        for i, v in enumerate(own[start - 1:], start=start):
            if name in (v.names or []):
                return i
        return 0

    @staticmethod
    def verb_perms(obj, vname: str) -> str:
        """The permission string of a verb, or empty when there is none."""
        try:
            for v in obj.verbs or []:
                if vname in (v.names or []):
                    return v.perms or ''
        except Exception:
            pass
        return ''

    @staticmethod
    def verb_code(obj, vname: str) -> List[str]:
        """A verb's source as a list of lines, which is how MOO returns it."""
        try:
            for v in obj.verbs or []:
                if vname in (v.names or []):
                    return (v.code or '').splitlines()
        except Exception:
            pass
        return []

    @staticmethod
    def verb_documentation(obj, vname: str) -> List[str]:
        """
        The documentation at the top of a verb.

        LambdaCore reads the leading bare strings, which are MOO's
        comments.  Verbs here are Python, so the docstring is the same
        thing in the same place; leading ``#`` comments count too, for
        verbs written without one.

        LambdaCore defaults to "the calling verb" via callers(), which has
        no equivalent here, so the object and verb name are required.
        """
        lines = CodeUtils.verb_code(obj, vname)
        if not lines:
            return []
        text = '\n'.join(lines).lstrip()
        for quote in ('"' * 3, "'" * 3):
            if text.startswith(quote):
                body = text[3:]
                end = body.find(quote)
                if end >= 0:
                    return body[:end].strip().splitlines()
        out = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('#'):
                out.append(stripped.lstrip('#').strip())
            elif stripped:
                break
        return out

    @staticmethod
    def verb_usage(obj, vname: str) -> str:
        """
        The usage line from a verb's documentation, if it has one.

        LambdaCore looks at the top of the code; the convention here is a
        ``Usage:`` line inside the docstring.
        """
        for line in CodeUtils.verb_documentation(obj, vname):
            if line.lower().startswith('usage'):
                return line.split(':', 1)[-1].strip()
        return ''

    # -- prepositions and argument specs ---------------------------------

    @staticmethod
    def get_prep(*args):
        """
        Pull a prepositional phrase off the front of *args*.

        LambdaCore: ``get_prep("in","front","of",...)`` gives
        ``{"in front of",...}``, and ``get_prep("frabulous",...)`` gives
        ``{"", "frabulous",...}`` -- an empty first element when the words
        are not a preposition.  Longest spelling wins, so "in front of"
        beats "in".
        """
        words = [str(a) for a in args]
        for group in CodeUtils.PREPS:
            for spelling in sorted(group.split('/'), key=len, reverse=True):
                parts = spelling.split()
                if len(parts) <= len(words) and words[:len(parts)] == parts:
                    return [group] + words[len(parts):]
        return [''] + words

    @staticmethod
    def parse_argspec(*args):
        """
        Read a verb argument specification off the front of *args*.

        LambdaCore: ``parse_argspec("this","in","front","of","any","foo")``
        gives ``{{"this","in front of","any"},{"foo"}}``.  Returns a string
        instead when it cannot parse, which is how the original reports an
        error.
        """
        words = [str(a) for a in args]
        if not words:
            return 'no arguments given'
        valid = ('this', 'any', 'none')
        dobj = words[0]
        if dobj not in valid:
            return f'"{dobj}" is not a valid argument specifier'
        rest = words[1:]
        if not rest:
            return [[dobj, 'none', 'none'], []]
        got = CodeUtils.get_prep(*rest)
        prep, rest = got[0], got[1:]
        if not prep:
            return [[dobj, 'none', 'none'], rest]
        if not rest:
            return [[dobj, prep, 'none'], []]
        iobj = rest[0]
        if iobj not in valid:
            return f'"{iobj}" is not a valid argument specifier'
        return [[dobj, prep, iobj], rest[1:]]

    # -- text -------------------------------------------------------------

    @staticmethod
    def substitute(text: str, subs) -> str:
        """
        Replace targets with substitutions, respecting word boundaries.

        LambdaCore: "Substitutes targets for subs in a delimited string
        fashion, avoiding substitution inside words."  A target beginning
        and ending with an alphanumeric matches whole words only; one that
        does not -- punctuation, say -- matches anywhere.
        """
        import re as _re
        out = str(text)
        for pair in subs or []:
            if not pair or len(pair) < 2:
                continue
            target, replacement = str(pair[0]), str(pair[1])
            if not target:
                continue
            delimited = target[0].isalnum() and target[-1].isalnum()
            pattern = _re.escape(target)
            if delimited:
                pattern = r'\b' + pattern + r'\b'
            out = _re.sub(pattern, replacement.replace('\\', '\\\\'), out)
        return out

    # -- tasks and players ------------------------------------------------

    @staticmethod
    def connected_players() -> List:
        """Everyone with a live connection."""
        try:
            from .network import _player_connections
            from .builtins import _database
        except Exception:
            return []
        out = []
        for num in list(_player_connections):
            try:
                obj = _database.get_object(num)
            except Exception:
                continue
            if obj is not None:
                out.append(obj)
        return out

    @staticmethod
    def task_valid(task_id) -> bool:
        """Whether a task is still queued or running."""
        try:
            from .tasks import get_task_queue
            q = get_task_queue()
        except Exception:
            return False
        return bool(q and (task_id in q.running_tasks
                           or task_id in q.suspended_tasks))

    @staticmethod
    def short_prep(prep: str) -> str:
        """The first spelling of a preposition group: ``at/to`` -> ``at``."""
        return (prep or '').split('/')[0]

    @staticmethod
    def full_prep(prep: str) -> str:
        """The whole group a preposition belongs to: ``to`` -> ``at/to``."""
        for group in CodeUtils.PREPS:
            if prep in group.split('/'):
                return group
        return prep or ''


#: Singletons, bound into the verb namespace the way su and ou are.
lu = ListUtils()
cu = CommandUtils()
cdu = CodeUtils()
