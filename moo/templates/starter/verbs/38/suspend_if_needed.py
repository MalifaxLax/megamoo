"""
suspend_if_needed on $command_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def suspend_if_needed(seconds: float = 0, *_):
        """
        Yield if the task has been running a while.

        In MOO this checks the remaining tick budget and suspends before
        the server kills the task.  There are no ticks here; what matters
        is the same though -- a long loop should let the world move -- so
        it yields unconditionally, which suspend(0) does cheaply.
        """
        try:
            from moo.verb_baton import suspend, holder
            if holder():
                suspend(seconds or 0)
        except Exception:
            pass


_a = kwargs.pop('_pyargs', None)

return suspend_if_needed(*(_a if _a is not None else argv), **kwargs)
