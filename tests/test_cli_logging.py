"""The CLI must run from a directory it cannot write to.

`moo.cli` opens `megamoo.log` in the working directory at *import* time.
That made an ordinary invocation from a read-only directory -- `megamoo
init mygame` run from `/`, which writes its game somewhere else entirely
-- die with an OSError traceback out of the logging module before argparse
had seen a single argument.
"""
import os
import stat
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(cwd):
    return subprocess.run(
        [sys.executable, '-c', 'import moo.cli; print("imported")'],
        cwd=cwd, capture_output=True, text=True,
        env={**os.environ, 'PYTHONPATH': ROOT},
    )


def test_importing_the_cli_works_in_a_writable_directory(tmp_path):
    r = _run(str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert 'imported' in r.stdout
    assert (tmp_path / 'megamoo.log').exists(), 'the log should still be written'


@pytest.mark.skipif(os.geteuid() == 0, reason='root can write anywhere')
def test_importing_the_cli_survives_a_read_only_directory(tmp_path):
    ro = tmp_path / 'readonly'
    ro.mkdir()
    os.chmod(ro, stat.S_IRUSR | stat.S_IXUSR)
    try:
        r = _run(str(ro))
        assert r.returncode == 0, f'import died: {r.stderr}'
        assert 'imported' in r.stdout
        # It says so once, on stderr, rather than dying.
        assert 'megamoo.log' in r.stderr
        assert 'Traceback' not in r.stderr
    finally:
        os.chmod(ro, stat.S_IRWXU)
