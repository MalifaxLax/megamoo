"""_docstring on $help_utils -- the leading docstring of a verb's source.

Three places in the old `help` verb opened with the same eight lines of
quote-hunting: the topic list, `help <verb>` and `help #obj.verb`.  One of
them is a verb now and the other two call it.

Hidden:  yes
Type:    function
"""


def _docstring(code):
    """The leading docstring of *code*, or '' if it has none."""
    stripped = (code or '').lstrip()
    for quote in ('"""', "'''"):
        if stripped.startswith(quote):
            end = stripped.find(quote, len(quote))
            if end > 0:
                return stripped[len(quote):end].strip()
    return ''


_a = kwargs.pop('_pyargs', None)

return _docstring(*(_a if _a is not None else argv), **kwargs)
