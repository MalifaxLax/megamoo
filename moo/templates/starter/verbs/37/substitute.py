"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

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


_a = kwargs.pop('_pyargs', None)

return substitute(*(_a if _a is not None else argv), **kwargs)
