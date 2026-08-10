"""The guide's verb count has to be the number `megamoo init` prints.

It has been wrong twice: 212 after the starter world was pruned, then 190
the moment @vfind was added. `init` prints the count of files it actually
copied, so the page and the terminal in front of the reader disagree the
instant anyone adds or removes a starter verb -- on the very first command
in the guide.

A number in prose that mirrors a number in code wants a test, or it goes
stale the third time too.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
GUIDE = ROOT / 'docs' / 'guide' / 'getting-started.html'
STARTER = ROOT / 'moo' / 'templates' / 'starter' / 'verbs'


@pytest.mark.skipif(not GUIDE.is_file() or not STARTER.is_dir(),
                    reason='guide or starter template not present')
def test_the_guide_quotes_the_real_verb_count():
    actual = len(list(STARTER.rglob('*.py')))
    quoted = {int(n) for n in re.findall(r'(\d+) verb files', GUIDE.read_text())}
    assert quoted, 'the guide stopped quoting a verb count; drop this test'
    assert quoted == {actual}, (
        f'getting-started.html says {sorted(quoted)} verb files, the starter '
        f'ships {actual} -- which is what `megamoo init` prints')
