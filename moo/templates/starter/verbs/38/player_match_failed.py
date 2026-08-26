"""
player_match_failed on $command_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

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



def player_match_failed(match_result, name: str, who=None) -> bool:
        """As object_match_failed, but phrased for people."""
        who = who or _player()
        if match_result is None or match_result in (-1, -2, -3):
            if who is not None:
                who.msg(f'I don\'t know anyone named "{name}".')
            return True
        return False


_a = kwargs.pop('_pyargs', None)

return player_match_failed(*(_a if _a is not None else argv), **kwargs)
