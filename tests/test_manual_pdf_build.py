"""`make-pdfs.sh` must name chapters that exist.

Its `FILES` list carried `08-orb-wars`, which is Shadowfall's chapter and
not in this repo. The script runs under `set -euo pipefail`, so the first
`perl` on the missing file killed the whole run -- after the per-chapter
PDFs but before the combined manual. That is why `docs/manual/pdf/` went
stale for several betas while the markdown moved on, and 0.10.0-beta21
shipped noting the script "wants fixing before the next docs build".

A build script that dies on a name is the cheapest possible thing to
assert, and nothing was asserting it.
"""
import pathlib
import re

import pytest

MANUAL = pathlib.Path(__file__).resolve().parent.parent / 'docs' / 'manual'
SCRIPT = MANUAL / 'make-pdfs.sh'


def _chapters():
    """The basenames in the script's FILES array."""
    if not SCRIPT.is_file():
        pytest.skip('make-pdfs.sh not present')
    text = SCRIPT.read_text(encoding='utf-8')
    m = re.search(r'^FILES=\((.*?)\)', text, re.S | re.M)
    assert m, 'FILES=( ... ) not found in make-pdfs.sh'
    names = m.group(1).replace('\\\n', ' ').split()
    assert names, 'FILES is empty'
    return names


def test_every_chapter_in_the_build_list_exists():
    missing = [n for n in _chapters() if not (MANUAL / f'{n}.md').is_file()]
    assert not missing, (
        f'make-pdfs.sh builds chapters with no markdown: {missing}. '
        'Under `set -e` the run dies there, and the combined manual never '
        'gets built.')


def test_every_chapter_markdown_is_in_the_build_list():
    """The other direction: a new chapter that never reaches the PDFs."""
    listed = set(_chapters())
    on_disk = {p.stem for p in MANUAL.glob('*.md')}
    # The merchant guide is a separate deliverable with its own stylesheet,
    # built outside this list.
    unlisted = on_disk - listed - {'merchant-guide'}
    assert not unlisted, f'chapters never built into a PDF: {sorted(unlisted)}'
