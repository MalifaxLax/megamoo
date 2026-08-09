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


def test_a_property_shadowing_a_verb_is_reported():
    """
    __getattr__ resolves properties before verbs, so a property named
    like a verb makes the verb unreachable through attribute access.
    Nothing fails at that point -- the failure is later, as
    `TypeError: 'str' object is not callable` at the call site, which
    names neither the property nor the verb.

    Reported at debug rather than warning on purpose: the shipped world
    collides five times deliberately, storing a verb's message in a
    property named after the verb.  This is here for the hour you would
    otherwise spend guessing which name was taken.
    """
    import io
    import logging
    import sqlite3

    from moo.database import Database
    from moo.objects import clear_shadow_reports

    world = (pathlib.Path(__file__).resolve().parent.parent
             / 'moo' / 'templates' / 'starter' / 'world.db')
    if not world.is_file():
        pytest.skip('starter world not present')

    import shutil, tempfile
    tmp = pathlib.Path(tempfile.mkdtemp()) / 'w.db'
    shutil.copy(world, tmp)
    db = Database(str(tmp), mode='readwrite')
    db.load()

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.DEBUG)
    log = logging.getLogger('megamoo.objects')
    log.addHandler(handler)
    old_level = log.level
    log.setLevel(logging.DEBUG)
    try:
        clear_shadow_reports()
        room = db.get_object(17)
        victim = next(v.names[0] for v in room.verbs if v.names)
        room.add_property(victim, 'not callable')
        room.invalidate_inheritance_cache(db)
        room._build_inheritance_cache(db)
        out = buf.getvalue()
        assert f'#17.{victim} is both a property' in out, out[:200]

        # ...and does not repeat on every rebuild.  The cache is rebuilt
        # whenever an ancestor changes, and a world can hold 60,000
        # objects; a message nobody can read is not a message.
        buf.truncate(0); buf.seek(0)
        room.invalidate_inheritance_cache(db)
        room._build_inheritance_cache(db)
        assert 'is both a property' not in buf.getvalue()
    finally:
        log.removeHandler(handler)
        log.setLevel(old_level)
        clear_shadow_reports()
