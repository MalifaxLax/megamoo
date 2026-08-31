"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

def _player():
    """The acting player, from the verb context, or None outside one."""
    try:
        from .verb_context import verb_ctx
        ctx = verb_ctx.get()
        return ctx[0] if ctx else None
    except Exception:
        return None



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


_a = kwargs.pop('_pyargs', None)

return object_match_failed(*(_a if _a is not None else argv), **kwargs)
