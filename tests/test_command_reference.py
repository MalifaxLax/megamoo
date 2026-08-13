"""The generated command reference has to match the commands that exist.

`tools/gen_command_reference.py` exists so this page cannot drift: it reads
names, levels and abbreviations straight from the shipped world. It has a
`--check` mode that reports drift and exits non-zero -- and nothing ever
called it. No test, no CI step. So the page went sixteen staff commands
stale and described one, @wearpos, that the starter has never shipped,
while the tool that would have said so sat unrun.

A tool nobody runs is a tool nobody runs. This runs it.

The three failures it catches are different and all real:

* a command in the world with no description -- someone added a command
  and the page does not mention it;
* a description for a command that is gone -- someone removed one and the
  page still advertises it;
* the page not matching what the generator would write now -- someone
  edited a description, or the world's levels or abbreviations changed,
  and nobody regenerated.
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))

STARTER_DB = ROOT / 'moo' / 'templates' / 'starter' / 'world.db'
PAGE = ROOT / 'docs' / 'guide' / 'commands.html'

pytestmark = pytest.mark.skipif(
    not STARTER_DB.is_file(), reason='starter template not present')


def _render():
    import gen_command_reference as gen
    commands = gen.read_commands(STARTER_DB)
    return gen.render(commands)


def test_every_shipped_command_is_described():
    _, undescribed, _ = _render()
    assert not undescribed, (
        'these commands ship but the guide does not describe them -- add them '
        'to GROUPS in tools/gen_command_reference.py: ' + ', '.join(undescribed))


def test_no_description_survives_its_command():
    _, _, vanished = _render()
    assert not vanished, (
        'the guide describes commands that are not in the shipped world, so it '
        'advertises what nobody can type: ' + ', '.join(vanished))


def test_the_page_is_what_the_generator_would_write():
    page, _, _ = _render()
    assert PAGE.read_text() == page, (
        f'{PAGE.relative_to(ROOT)} is out of date -- run '
        '`python3 tools/gen_command_reference.py` and commit the result.')
