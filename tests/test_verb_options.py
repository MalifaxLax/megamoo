"""
@adverb's options, and why it must not read dobj/prep/iobj.

`=` is a preposition.  The parser splits on it before a verb runs, so
`@adverb #3.x with rx auth=3` arrived with prep='=' and never 'with' --
and the verb, looking for 'with', fell through to its no-options branch
and took the whole remainder as the verb's *name*.  It created a verb
called `x with rx auth=3`, listed it in @verbs, and said "added".

The fix is to read argstr, the full unsplit argument string.  These
tests pin that down, because the natural way to write this verb is the
broken way.
"""

import pathlib
import re

import pytest

VERB = (pathlib.Path(__file__).resolve().parent.parent
        / 'moo' / 'templates' / 'starter' / 'verbs' / '3' / '@adverb.py')

pytestmark = pytest.mark.skipif(not VERB.is_file(), reason='starter template absent')


def test_it_parses_argstr_not_the_split_arguments():
    src = VERB.read_text()
    assert 'argstr' in src, '@adverb must read argstr'
    # Code only.  The comments explain the dobj/iobj trap by name, and a
    # check that cannot tell prose from code fails on its own explanation.
    body = src.split('"""', 2)[-1]
    code = '\n'.join(l for l in body.splitlines()
                     if l.strip() and not l.strip().startswith('#'))
    for split_var in ('dobj', 'iobj'):
        assert not re.search(rf'\b{split_var}\b', code), (
            f'@adverb reads {split_var}, which the "=" preposition split '
            f'has already mangled')


def test_the_documented_options_are_the_parsed_ones():
    """
    The docstring and the parser drifted apart once already: the options
    were documented, unreachable, and left in place for months.
    """
    src = VERB.read_text()
    doc = src.split('"""')[1]
    for opt in ('min=N', 'auth=N', 'base'):
        assert opt in doc, f'{opt} is parsed but not documented'
    for opt in ("startswith('min=')", "startswith('auth=')", "p == 'base'"):
        assert opt in src, f'{opt} is documented but not parsed'


def test_every_example_in_the_docstring_would_parse():
    """
    Each example is split the way the verb splits it, and must yield a
    spec containing a dot -- which is what the verb requires before it
    will do anything.
    """
    doc = VERB.read_text().split('"""')[1]
    examples = [l.strip() for l in doc.splitlines()
                if l.strip().startswith('@adverb')]
    assert examples, 'no examples to check'
    for ex in examples:
        argstr = ex.split(None, 1)[1] if ' ' in ex else ''
        spec = argstr.partition(' with ')[0].strip()
        assert '.' in spec, f'example would be rejected: {ex}'
