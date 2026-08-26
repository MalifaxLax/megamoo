"""
verb_usage on $code_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def verb_usage(obj, vname: str) -> str:
        """
        The usage line from a verb's documentation, if it has one.

        LambdaCore looks at the top of the code; the convention here is a
        ``Usage:`` line inside the docstring.
        """
        for line in call_verb(this, 'verb_documentation', obj, vname):
            if line.lower().startswith('usage'):
                return line.split(':', 1)[-1].strip()
        return ''


_a = kwargs.pop('_pyargs', None)

return verb_usage(*(_a if _a is not None else argv), **kwargs)
