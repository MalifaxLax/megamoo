"""
parse_argspec on $code_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

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
        got = call_verb(this, 'get_prep', *rest)
        prep, rest = got[0], got[1:]
        if not prep:
            return [[dobj, 'none', 'none'], rest]
        if not rest:
            return [[dobj, prep, 'none'], []]
        iobj = rest[0]
        if iobj not in valid:
            return f'"{iobj}" is not a valid argument specifier'
        return [[dobj, prep, iobj], rest[1:]]


_a = kwargs.pop('_pyargs', None)

return parse_argspec(*(_a if _a is not None else argv), **kwargs)
