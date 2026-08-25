"""
verb_documentation on $code_utils.

Ported from `moo.moo_libs` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

from typing import Any, List, Optional



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
        lines = call_verb(this, 'verb_code', obj, vname)
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


_a = kwargs.pop('_pyargs', None)

return verb_documentation(*(_a if _a is not None else argv), **kwargs)
