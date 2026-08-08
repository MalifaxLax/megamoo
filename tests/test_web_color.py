"""tests/test_web_color.py — MOO/ANSI to HTML conversion for the browser.

The web transport is the one place game text becomes markup, so the
escaping rules matter: everything that is not a colour code the converter
recognises must arrive as inert text.
"""
from moo.web.color import moo_colors_to_html, ansi_to_html


# ---------------------------------------------------------------------------
#   MOO % codes
# ---------------------------------------------------------------------------

def test_basic_code_becomes_span():
    assert moo_colors_to_html('&r!alert&n done') == \
        '<span class="cr">!alert</span> done'


def test_letter_after_code_means_it_is_not_a_code():
    # Both transports guard single-letter codes with (?![a-zA-Z]) so an
    # ordinary word starting after a percent survives intact; the web
    # converter must agree with moo/color.py or the same game text would
    # render differently on telnet and in the browser.
    assert moo_colors_to_html('%rate limit') == '%rate limit'


def test_xterm_256_and_hex():
    assert moo_colors_to_html('&<245>dim&n') == '<span class="c245">dim</span>'
    assert moo_colors_to_html('&<#FF0000>red&n') == \
        '<span style="color:#FF0000">red</span>'


def test_doubled_sigil_is_a_literal_sigil():
    assert moo_colors_to_html('100&&') == '100&'


def test_a_bare_percent_is_ordinary_text():
    """
    The reason the sigil moved off '%' at all.

    While '%' introduced colour, a literal per-cent sign in game text had
    to be escaped, and '"%<245>%s" % name' raised ValueError -- Python's
    formatting operator colliding with the engine's display syntax.  It
    must now survive untouched.
    """
    assert moo_colors_to_html('50% off') == '50% off'
    assert moo_colors_to_html('100%') == '100%'


def test_markup_in_game_text_is_escaped():
    # A player naming themselves with a tag must not inject markup.
    assert '<script>' not in moo_colors_to_html('<script>alert(1)</script>')
    assert '&lt;script&gt;' in moo_colors_to_html('<script>alert(1)</script>')


def test_unclosed_spans_are_closed_at_end():
    assert moo_colors_to_html('&r!danger').endswith('</span>')


# ---------------------------------------------------------------------------
#   ANSI (the raw=True path: login splash, terminal frames)
# ---------------------------------------------------------------------------

def test_sgr_colour_becomes_span():
    assert ansi_to_html('\x1b[31mred\x1b[0m') == '<span class="cr">red</span>'


def test_xterm_256_foreground():
    # 38;5;94 is the brown rock the grid renderer uses.
    assert ansi_to_html('\x1b[38;5;94m##\x1b[0m') == \
        '<span class="c94">##</span>'


def test_cursor_and_clear_sequences_are_dropped():
    # A full-screen frame's positioning codes have no meaning in a
    # scrollback pane; they must not appear as visible garbage.
    out = ansi_to_html('\x1b[2J\x1b[H\x1b[Khello')
    assert out == 'hello'


def test_ansi_path_still_escapes_markup():
    assert ansi_to_html('<b>bold</b>') == '&lt;b&gt;bold&lt;/b&gt;'


def test_lone_reset_does_not_emit_stray_close_tags():
    # login.py leads the splash with a bare reset while nothing is open.
    assert ansi_to_html('\x1b[0mMegaMOO') == 'MegaMOO'


def test_ansi_embedded_in_moo_coded_text():
    """Verbs mix both notations, so one pass has to understand both.

    moo verbs/15/rlook.py emits a MOO-coded line whose exit list carries a
    literal \\x1b[38;5;245m to restore dim gray after the telnet clickable
    handling resets it.  That escape reached the browser as invisible junk
    in the middle of the sentence.
    """
    out = moo_colors_to_html('&<245>Obvious Exits: `south`\x1b[38;5;245m&n')
    assert '\x1b' not in out
    assert out.count('<span class="c245">') == 2
    assert 'Obvious Exits: `south`' in out


def test_ansi_colour_before_a_letter_still_renders():
    # "\x1b[31mred" cannot be routed through the MOO notation first: "&r"
    # followed by a letter is deliberately not a code, so the colour would
    # silently vanish.
    assert moo_colors_to_html('\x1b[31mred') == '<span class="cr">red</span>'


def test_ansi_reset_closes_moo_opened_spans():
    out = moo_colors_to_html('&<245>dim\x1b[0mplain')
    assert out == '<span class="c245">dim</span>plain'


def test_percent_in_raw_terminal_output_stays_literal():
    # A splash screen or progress bar's % is an ordinary character.
    assert ansi_to_html('50% done') == '50% done'


def test_unclosed_ansi_span_is_closed_at_end():
    assert ansi_to_html('\x1b[32mgreen').endswith('</span>')
    assert ansi_to_html('\x1b[32mgreen').count('</span>') == 1
