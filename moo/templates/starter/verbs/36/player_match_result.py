"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

def player_match_result(results, names, who=None) -> bool:
        """Report on a batch of player matches; True if any failed."""
        bad = False
        for result, name in zip(results or [], names or []):
            if call_verb(this, 'player_match_failed', result, name, who):
                bad = True
        return bad


_a = kwargs.pop('_pyargs', None)

return player_match_result(*(_a if _a is not None else argv), **kwargs)
