"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

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


_a = kwargs.pop('_pyargs', None)

return yes_or_no(*(_a if _a is not None else argv), **kwargs)
