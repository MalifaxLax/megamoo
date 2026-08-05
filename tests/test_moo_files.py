"""
The file builtins, and the containment that makes them safe to have.

The verb sandbox already allows `import` and `open`, so these add no
capability a verb lacked.  The point is the opposite: importing somebody
else's core should not hand their verbs the filesystem, and "it only
touches files under one directory you chose" is a claim worth being able
to make about thousands of verbs nobody has read.
"""

import os
import tempfile

import pytest

from moo import moo_files as mf
from moo.properties import MOOError


@pytest.fixture
def root(tmp_path):
    mf.set_files_root(str(tmp_path))
    yield tmp_path
    mf.set_files_root(None)


# --------------------------------------------------------------------------
# Containment
# --------------------------------------------------------------------------

def test_disabled_until_a_root_is_set():
    # A server that has not said where these files go has not agreed to
    # have them.
    mf.set_files_root(None)
    with pytest.raises(MOOError):
        mf.fileread('anywhere', 'anything')


def test_dot_dot_cannot_escape(root):
    (root.parent / 'SECRET').write_text('no')
    with pytest.raises(MOOError):
        mf.fileread('..', 'SECRET')


def test_a_buried_dot_dot_cannot_escape(root):
    # The check is on the resolved path, not the string, so a `..` in the
    # middle is caught as surely as one at the front.
    with pytest.raises(MOOError):
        mf.filewrite('a/b/../../..', 'pwned', ['x'])


def test_an_absolute_path_is_refused(root):
    # It would be contained anyway -- "/etc" strips to "etc" and lands
    # under the root -- but silently reading root/etc/passwd when a verb
    # asked for /etc/passwd is a confusing way to be safe.
    with pytest.raises(MOOError):
        mf.fileread('/etc', 'passwd')


def test_a_symlink_out_is_refused(root):
    # A string check would pass this; resolving the path is what catches it.
    outside = root.parent / 'outside.txt'
    outside.write_text('secret')
    os.symlink(str(outside), str(root / 'link.txt'))
    with pytest.raises(MOOError):
        mf.fileread('.', 'link.txt')


def test_rename_cannot_write_outside(root):
    mf.filewrite('.', 'a', ['x'])
    with pytest.raises(MOOError):
        mf.filerename('.', 'a', '../../escaped')


# --------------------------------------------------------------------------
# The API Inferno actually calls
# --------------------------------------------------------------------------

def test_append_then_read(root):
    assert mf.fileappend('inferno', 'PvPLog', ['one', 'two']) == 1
    assert mf.fileread('inferno', 'PvPLog') == ['one', 'two']


def test_append_creates_the_directory(root):
    # The callers are logs.  A log that fails because nobody made its
    # directory is worse than one that makes it.
    mf.fileappend('deep/nested/path', 'log', ['x'])
    assert mf.fileread('deep/nested/path', 'log') == ['x']


def test_a_missing_file_reads_as_empty(root):
    # Callers test the result for emptiness rather than catching.
    assert mf.fileread('nowhere', 'nothing') == []
    assert mf.filelength('nowhere', 'nothing') == 0


def test_write_replaces_the_whole_file(root):
    mf.filewrite('d', 'f', ['a', 'b', 'c'])
    assert mf.fileread('d', 'f') == ['a', 'b', 'c']


def test_write_with_start_and_count_splices(root):
    # `filewrite(dir, file, {}, 1, n)` is how the callers delete a range.
    mf.filewrite('d', 'f', ['a', 'b', 'c', 'd'])
    mf.filewrite('d', 'f', [], 1, 2)
    assert mf.fileread('d', 'f') == ['c', 'd']


def test_the_splice_start_is_one_based(root):
    # MOO counts from one, and this is an argument rather than a
    # subscript, so @port does not shift it -- the conversion is here.
    mf.filewrite('d', 'f', ['a', 'b', 'c'])
    mf.filewrite('d', 'f', ['X'], 2, 1)
    assert mf.fileread('d', 'f') == ['a', 'X', 'c']


def test_filelist_returns_files_then_directories(root):
    # Callers read them as [1] and [2], so the order is load-bearing.
    mf.filewrite('top', 'afile', ['x'])
    mf.filemkdir('top', 'adir')
    files, dirs = mf.filelist('top')
    assert files == ['afile'] and dirs == ['adir']


def test_filelist_of_a_missing_directory_is_empty(root):
    assert mf.filelist('no/such') == [[], []]


def test_exists_and_delete(root):
    mf.filewrite('d', 'f', ['x'])
    assert mf.fileexists('d', 'f') == 1
    assert mf.filedelete('d', 'f') == 1
    assert mf.fileexists('d', 'f') == 0
    assert mf.filedelete('d', 'f') == 0        # already gone, not an error
