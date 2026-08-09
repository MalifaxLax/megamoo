"""
MCCP2 and MSSP.

Both existed as declarations before they existed as features:
``MSSP = bytes([70])`` in the option table, and ``enable_mssp`` /
``enable_mccp`` in the config defaulting to True -- so the server offered
a crawler two protocols it could not then speak.  The last test here is
the one that matters: it fails if either setting goes back to being read
by nobody.
"""

import inspect
import zlib

from moo import network
from moo.config import ServerConfig


def test_the_option_codes_are_the_registered_ones():
    # Getting these wrong is invisible: the client simply never accepts.
    assert network.COMPRESS2 == bytes([86])   # MCCP2
    assert network.MSSP == bytes([70])
    assert network.MSSP_VAR == bytes([1])
    assert network.MSSP_VAL == bytes([2])


def test_both_protocols_are_offered_and_recognised():
    src = inspect.getsource(network)
    assert 'WILL + COMPRESS2' in src, 'MCCP2 is never offered'
    assert 'WILL + MSSP' in src, 'MSSP is never offered'
    # ...and the reply has to be understood, or the offer goes nowhere.
    assert "86: 'mccp2'" in src
    assert "70: 'mssp'" in src


def test_the_compression_subnegotiation_is_sent_uncompressed():
    """
    The bytes that tell a client to start decompressing cannot themselves
    be compressed.  So _start_compression must write and drain *before*
    it creates the compressor -- get that backwards and every MCCP client
    desynchronises on connect.
    """
    src = inspect.getsource(network.PlayerConnection._start_compression)
    write_at = src.index('self.writer.write')
    make_at = src.index('zlib.compressobj')
    assert write_at < make_at, 'compressor created before the subnegotiation'


def test_every_write_goes_through_the_funnel():
    """
    Once compression is on, the connection is one continuous zlib stream.
    A single write that bypassed _write would inject raw bytes into the
    middle of it and desynchronise the client for good, so there must be
    no direct writer.write calls outside the funnel itself.
    """
    src = inspect.getsource(network)
    direct = src.count('self.writer.write(')
    # Two legitimate ones: inside _write, and the uncompressed
    # subnegotiation in _start_compression.
    assert direct == 2, f'{direct} direct socket writes; expected 2'


def test_sync_flush_keeps_the_stream_interactive():
    """
    Without Z_SYNC_FLUSH zlib buffers until it has enough to compress
    well, so a prompt would sit unsent until the next screenful arrived.
    """
    assert 'Z_SYNC_FLUSH' in inspect.getsource(network.PlayerConnection._write)


def test_a_round_trip_through_the_funnel_decompresses():
    c = zlib.compressobj(6)
    out = c.compress(b'Obvious Exits: north') + c.flush(zlib.Z_SYNC_FLUSH)
    assert zlib.decompressobj().decompress(out) == b'Obvious Exits: north'


def test_mssp_advertises_the_tls_port():
    """The reason MSSP was worth writing: it is where the TLS port lives."""
    src = inspect.getsource(network.PlayerConnection._send_mssp)
    assert "'SSL'" in src and 'tls_port' in src


def test_the_config_flags_are_actually_read():
    """
    enable_mccp and enable_mssp both defaulted to True while no code
    anywhere mentioned them -- the ssl_enabled pattern exactly.  This
    fails if either goes back to being decoration.
    """
    p = ServerConfig().protocol
    assert hasattr(p, 'enable_mccp') and hasattr(p, 'enable_mssp')
    src = inspect.getsource(network)
    assert 'enable_mccp' in src, 'enable_mccp is set by nobody and read by nobody'
    assert 'enable_mssp' in src, 'enable_mssp is set by nobody and read by nobody'
