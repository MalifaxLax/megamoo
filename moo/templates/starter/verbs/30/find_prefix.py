"""
find_prefix on $string_utils.

Ported from `moo.string_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def find_prefix(prefix, candidates):
        """
        Index of the one candidate *prefix* matches, else -1.

        MOO: ``$string_utils:find_prefix``.  An exact match wins outright;
        otherwise a prefix must be unambiguous, so -1 means either nothing
        matched or several did.  This is the rule the MOO command parser
        uses, and the reason abbreviations behave predictably.
        """
        p = str(prefix).lower()
        cands = [str(c).lower() for c in candidates]
        if p in cands:
            return cands.index(p)
        hits = [i for i, c in enumerate(cands) if c.startswith(p)]
        return hits[0] if len(hits) == 1 else -1


_a = kwargs.pop('_pyargs', None)

return find_prefix(*(_a if _a is not None else argv), **kwargs)
