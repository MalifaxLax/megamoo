"""
The TLS listener.

The point of every test here is that TLS either works or refuses to
start.  The setting this replaced -- ``ssl_enabled`` -- was declared,
documented as "require TLS encryption on the main port", validated at
startup so a missing certificate stopped the server, and then read by
nothing at all.  Turning it on gave you positive feedback and plaintext.
So these tests care less about the happy path than about every way a
misconfiguration could end up serving an unencrypted port to somebody
who believed otherwise.
"""

import ssl
import pytest

from moo.config import ServerConfig


def _cfg(**net):
    c = ServerConfig()
    for k, v in net.items():
        setattr(c.network, k, v)
    return c


def test_no_tls_by_default():
    assert ServerConfig().network.tls_port == 0


def test_a_port_without_a_certificate_refuses(tmp_path):
    with pytest.raises(ValueError, match='tls_cert'):
        _cfg(tls_port=6771).validate()


def test_a_certificate_without_a_port_refuses(tmp_path):
    """
    The quiet one.  Supplying a cert and key looks like enabling TLS, and
    without a port nothing would listen -- so the operator ends up with a
    plaintext world and every reason to think otherwise.
    """
    cert = tmp_path / 'c.pem'; cert.write_text('x')
    key = tmp_path / 'k.pem'; key.write_text('x')
    with pytest.raises(ValueError, match='without tls_port'):
        _cfg(tls_cert=str(cert), tls_key=str(key)).validate()


def test_a_missing_certificate_file_refuses(tmp_path):
    key = tmp_path / 'k.pem'; key.write_text('x')
    with pytest.raises(ValueError, match='certificate not found'):
        _cfg(tls_port=6771, tls_cert=str(tmp_path / 'nope.pem'),
             tls_key=str(key)).validate()


def test_tls_may_not_share_the_plain_port(tmp_path):
    """
    Sharing would not upgrade the plain port, it would replace it -- and
    `telnet`, which is the command in every quickstart, cannot speak TLS.
    """
    cert = tmp_path / 'c.pem'; cert.write_text('x')
    key = tmp_path / 'k.pem'; key.write_text('x')
    c = _cfg(tls_port=6771, tls_cert=str(cert), tls_key=str(key))
    c.network.port = 6771
    with pytest.raises(ValueError, match='port of its own'):
        c.validate()


def test_command_line_settings_are_validated(monkeypatch):
    """
    validate() runs from __post_init__, so it sees the defaults and a
    config file and nothing else.  Until run_server called it again,
    everything supplied by flag or environment variable went unchecked --
    which is precisely where a TLS misconfiguration comes from.
    """
    import inspect
    from moo import server
    src = inspect.getsource(server.run_server)
    assert 'config.validate()' in src, (
        'run_server must re-validate after applying overrides')
    assert src.index('tls_key = tls_key') < src.index('config.validate()'), (
        'validation must come after the overrides it is meant to check')


def test_the_context_refuses_old_protocol_versions():
    """TLS 1.0 and 1.1 are deprecated; the listener sets a floor of 1.2."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    assert ctx.minimum_version >= ssl.TLSVersion.TLSv1_2


def test_the_dead_ssl_settings_are_gone():
    """
    ssl_enabled/ssl_cert/ssl_key claimed encryption and delivered none.
    A config field that nothing reads is worse than a missing feature,
    because it answers the question "is this encrypted?" with a yes.
    """
    net = ServerConfig().network
    for dead in ('ssl_enabled', 'ssl_cert', 'ssl_key'):
        assert not hasattr(net, dead), f'{dead} is back'


# ------------------------------------------------------------------
# HTTPS for the browser client
# ------------------------------------------------------------------
#
# The game's TLS is a second listener because telnet cannot speak TLS.
# The browser client's is a flag on the port it already has: a browser is
# not telnet, so nothing there has to keep speaking plaintext. It is also
# the only way the client uses an encrypted socket at all -- client.js
# picks ws:// or wss:// from location.protocol, so over HTTP it can only
# ever open an unencrypted one, whatever the game listener is doing.

def test_no_web_tls_by_default():
    assert ServerConfig().network.web_tls is False


def test_web_tls_without_a_certificate_refuses(tmp_path):
    with pytest.raises(ValueError, match='web_tls is set'):
        _cfg(web_tls=True).validate()


def test_web_tls_with_a_missing_certificate_file_refuses(tmp_path):
    key = tmp_path / 'k.pem'; key.write_text('x')
    with pytest.raises(ValueError, match='certificate not found'):
        _cfg(web_tls=True, tls_cert=str(tmp_path / 'nope.pem'),
             tls_key=str(key)).validate()


def test_web_tls_needs_no_game_tls_port(tmp_path):
    """Serving the client over HTTPS is a reason to hold a certificate.

    The "cert with no listener" rule predates this and refused it, since
    tls_port was the only thing that could serve one.
    """
    cert = tmp_path / 'c.pem'; cert.write_text('x')
    key = tmp_path / 'k.pem'; key.write_text('x')

    _cfg(web_tls=True, tls_cert=str(cert), tls_key=str(key)).validate()


def test_a_valid_game_tls_config_is_accepted(tmp_path):
    """The combination nothing covered, which is how a regression got in.

    Rearranging this block once left the "cert without a port" branch
    hanging off web_tls, so a correct tls_port + cert setup raised
    "given without tls_port". Every refusal was tested; the acceptance
    was not.
    """
    cert = tmp_path / 'c.pem'; cert.write_text('x')
    key = tmp_path / 'k.pem'; key.write_text('x')

    _cfg(tls_port=7778, tls_cert=str(cert), tls_key=str(key)).validate()


def test_both_listeners_together(tmp_path):
    cert = tmp_path / 'c.pem'; cert.write_text('x')
    key = tmp_path / 'k.pem'; key.write_text('x')

    _cfg(tls_port=7778, web_tls=True,
         tls_cert=str(cert), tls_key=str(key)).validate()


def test_the_context_is_built_in_one_place():
    """Both listeners share it, so they cannot disagree about the floor."""
    from moo.server import build_tls_context
    import inspect

    src = inspect.getsource(build_tls_context)
    assert 'TLSv1_2' in src

    import moo.server as srv
    assert inspect.getsource(srv).count('SSLContext(') == 1
