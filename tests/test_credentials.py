"""Passwords, and the wizard account every new world gets.

These exist because a mutation audit found that `check_password` could be
made to `return True` as its first line and the whole suite still passed
-- 441 tests, none of which ever asked whether a wrong password is
rejected. The same was true of the wizard flag on eval_python, which is
the last line of defence against arbitrary code execution in the server
process.

Both directions on every rule: a wrong password must be refused *and* a
right one accepted. A test that only covers the refusal lets a validator
that refuses everything pass, which is how the TLS accept path broke.
"""
import json
import sqlite3
import sys

import pytest

from moo.login import PBKDF2_ROUNDS, check_password, hash_password


# ------------------------------------------------------------------
# Hashing
# ------------------------------------------------------------------

def test_the_right_password_is_accepted():
    assert check_password('correct horse', hash_password('correct horse'))


def test_a_wrong_password_is_refused():
    assert not check_password('wrong', hash_password('correct horse'))


def test_the_hash_is_not_the_plaintext():
    """A mutation returning the plaintext passed the entire suite."""
    stored = hash_password('correct horse')

    assert 'correct horse' not in stored


def test_the_same_password_hashes_differently_each_time():
    """Salted: two accounts sharing a password must not share a hash."""
    assert hash_password('same') != hash_password('same')


def test_hashes_are_stretched():
    """The point of the format change.

    An unstretched SHA-256 is tried at billions of guesses a second on a
    GPU; the wizard password shipped in the PyPI wheel was recovered from
    its hash in under a second with a short word list.
    """
    stored = hash_password('x')

    assert stored.startswith('$pbkdf2$')
    assert PBKDF2_ROUNDS >= 600_000
    assert str(PBKDF2_ROUNDS) in stored


def test_a_corrupted_hash_refuses_rather_than_crashing():
    for broken in ('$pbkdf2$', '$pbkdf2$notanumber$salt$digest', '$pbkdf2$1$x',
                   'garbage', '$unknown$a$b'):
        assert check_password('anything', broken) is False


def test_legacy_sha256_hashes_still_verify():
    """Worlds created before the change must keep working.

    hash_password never produces this format again, so accounts convert
    as their owners change passwords.
    """
    import hashlib
    salt = 'ab' * 16
    digest = hashlib.sha256((salt + 'old secret').encode()).hexdigest()
    legacy = f'$sha256${salt}${digest}'

    assert check_password('old secret', legacy) is True
    assert check_password('wrong', legacy) is False


# ------------------------------------------------------------------
# The wizard account a new world ships with
# ------------------------------------------------------------------

def _wizard_hash(game_dir):
    db = sqlite3.connect(f'file:{game_dir}/world.db?mode=ro', uri=True)
    try:
        row = db.execute("select value from properties "
                         "where objnum=100 and name='password'").fetchone()
    finally:
        db.close()
    return json.loads(row[0]) if row else None


def test_each_world_gets_its_own_wizard_password(tmp_path):
    """The one that mattered most.

    Every world used to ship the template's hash unchanged, so every
    install shared a wizard password -- and the hash was in the wheel.
    """
    from moo.init import init_game

    init_game(str(tmp_path / 'a'))
    init_game(str(tmp_path / 'b'))

    assert _wizard_hash(tmp_path / 'a') != _wizard_hash(tmp_path / 'b')


def test_the_old_shipped_password_no_longer_works(tmp_path):
    from moo.init import init_game

    init_game(str(tmp_path / 'g'))

    assert not check_password('megamoo', _wizard_hash(tmp_path / 'g'))
    assert not check_password('wizard', _wizard_hash(tmp_path / 'g'))


def test_the_generated_password_actually_logs_in(tmp_path, capsys):
    """Generating a password nobody can use would be worse than the bug."""
    from moo.init import init_game

    init_game(str(tmp_path / 'g'))
    printed = capsys.readouterr().out

    line = [l for l in printed.splitlines() if 'Wizard login:' in l]
    assert line, f'init did not print the password:\n{printed}'
    password = line[0].split('/')[-1].strip()

    assert check_password(password, _wizard_hash(tmp_path / 'g'))


def test_the_shipped_template_carries_no_usable_secret():
    """A hash in the package is a secret in the package."""
    from moo.init import template_dir

    stored = _wizard_hash(template_dir())

    assert not check_password('megamoo', stored)
    assert not check_password('wizard', stored)


# ------------------------------------------------------------------
# Arbitrary code execution
# ------------------------------------------------------------------

def test_eval_python_refuses_a_non_wizard():
    """The last line of defence for RCE, previously untested.

    eval_python and exec_python are in *every verb's* namespace, so the
    gm4 guard on the `eval` verb is not the only route to them.
    """
    from types import SimpleNamespace
    from moo.builtins import eval_python, exec_python

    ordinary = SimpleNamespace(has_flag=lambda flag: False, objnum=42)

    with pytest.raises(PermissionError):
        eval_python('1 + 1', {'player': ordinary})
    with pytest.raises(PermissionError):
        exec_python('x = 1', {'player': ordinary})


def test_eval_python_refuses_when_there_is_no_player():
    from moo.builtins import eval_python

    with pytest.raises(PermissionError):
        eval_python('1 + 1', {})


def test_eval_python_still_works_for_a_wizard():
    """The accept path -- without it, a check that refuses everyone passes."""
    from types import SimpleNamespace
    from moo.builtins import eval_python

    wizard = SimpleNamespace(has_flag=lambda flag: True, objnum=100)

    assert eval_python('40 + 2', {'player': wizard}) == 42
