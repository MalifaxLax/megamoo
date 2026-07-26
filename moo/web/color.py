"""
MOO Color Code to HTML Converter

This module converts MOO ``%``-prefixed color codes into HTML
``<span>`` tags with CSS classes.  The actual color values (hex codes,
RGB values) are defined in ``client.css`` on the web client side, not
in this module -- this module only generates the class names.

Color code syntax
-----------------

**Basic codes** (single letter after ``%``)::

    %r  -> <span class="cr">  (red)
    %G  -> <span class="cG">  (bright green)
    %h  -> <span class="ch">  (highlight/bold)
    %n  -> closes all open spans (reset)

**Extended codes** (``%<...>`` syntax)::

    %<123>      -> <span class="c123">    (xterm-256 color)
    %<#FF0000>  -> <span style="color:#FF0000">  (hex color)
    %<bg245>    -> <span class="bg245">   (xterm-256 background)
    %<bg#00FF00> -> <span style="background-color:#00FF00">

**Escaped percent** -- ``%%`` produces a literal ``%`` character.

Basic color code mapping
------------------------

=========  ===========  ===========================
Code       CSS Class    Typical Color
=========  ===========  ===========================
``%x``     ``cx``       Dark gray / black
``%r``     ``cr``       Red
``%g``     ``cg``       Green
``%y``     ``cy``       Yellow / brown
``%b``     ``cb``       Blue
``%m``     ``cm``       Magenta
``%c``     ``cc``       Cyan
``%w``     ``cw``       White / light gray
``%X``     ``cX``       Bright black (dark gray)
``%R``     ``cR``       Bright red
``%G``     ``cG``       Bright green
``%Y``     ``cY``       Bright yellow
``%B``     ``cB``       Bright blue
``%M``     ``cM``       Bright magenta
``%C``     ``cC``       Bright cyan
``%W``     ``cW``       Bright white
``%h``     ``ch``       Highlight / bold
``%u``     ``cu``       Underline
``%f``     ``cf``       Flash / blink
``%i``     ``ci``       Italic / inverse
=========  ===========  ===========================

Architecture
------------

This module is called by ``WebSocketConnection.send()`` in
``connection.py`` to convert outgoing messages from internal MOO color
format to browser-renderable HTML.  The telnet equivalent uses ANSI
escape codes instead (handled by the telnet connection module).
"""

import re
import html as _html


# =============================================================================
# Basic Color Code Mapping
# =============================================================================

# Maps single-character MOO color codes to CSS class names.
# Lowercase = normal intensity, uppercase = bright/bold.
# Special codes: h=highlight, u=underline, f=flash, i=italic.
_BASIC_CLASSES = {
    'x': 'cx',   'r': 'cr',   'g': 'cg',   'y': 'cy',
    'b': 'cb',   'm': 'cm',   'c': 'cc',   'w': 'cw',
    'X': 'cX',   'R': 'cR',   'G': 'cG',   'Y': 'cY',
    'B': 'cB',   'M': 'cM',   'C': 'cC',   'W': 'cW',
    'h': 'ch',   'u': 'cu',   'f': 'cf',   'i': 'ci',
}


# =============================================================================
# Public API
# =============================================================================

def moo_colors_to_html(text: str) -> str:
    """
    Convert MOO color codes in *text* to HTML spans with CSS classes.

    Performs a single-pass walk through the raw text character by
    character.  Text content is HTML-escaped (``&``, ``<``, ``>``
    are converted to entities) while color codes are converted to
    ``<span>`` tags.  All open spans are automatically closed at the
    end of the string.

    Args:
        text: Raw text containing MOO ``%`` color codes.

    Returns:
        HTML string with ``<span>`` tags replacing color codes.
        All text content is properly HTML-escaped.

    Examples::

        moo_colors_to_html('%rHello%n world')
        # '<span class="cr">Hello</span> world'

        moo_colors_to_html('100%%')
        # '100%'

        moo_colors_to_html('%<#FF0000>red%n')
        # '<span style="color:#FF0000">red</span>'
    """
    # Replace escaped %% with a null-byte placeholder before processing,
    # so we don't accidentally interpret it as a color code
    PLACEHOLDER = '\x00PCT\x00'
    text = text.replace('%%', PLACEHOLDER)

    result = []
    open_spans = 0  # Track number of open <span> tags for proper closing
    pos = 0

    while pos < len(text):
        # --- Try extended code: %<...> ---
        if text[pos] == '%' and pos + 1 < len(text) and text[pos + 1] == '<':
            close = text.find('>', pos + 2)
            if close != -1:
                inner = text[pos + 2:close]
                tag = _extended_to_span(inner)
                if tag:
                    result.append(tag)
                    open_spans += 1
                    pos = close + 1
                    continue

        # --- Try basic code: %X (single letter) ---
        if text[pos] == '%' and pos + 1 < len(text) and text[pos + 1].isalpha():
            # Ensure this is a single-letter code, not a multi-letter word
            # (the next-next char must not be alphabetic)
            next_next = text[pos + 2] if pos + 2 < len(text) else ''
            if not next_next.isalpha():
                code = text[pos + 1]
                if code == 'n':
                    # %n = reset: close all currently open spans
                    result.append('</span>' * open_spans)
                    open_spans = 0
                    pos += 2
                    continue
                cls = _BASIC_CLASSES.get(code)
                if cls:
                    result.append(f'<span class="{cls}">')
                    open_spans += 1
                    pos += 2
                    continue

        # --- Regular character -- HTML-escape it ---
        ch = text[pos]
        if ch == PLACEHOLDER[0] and text[pos:pos + len(PLACEHOLDER)] == PLACEHOLDER:
            # Restore escaped %% as a literal %
            result.append('%')
            pos += len(PLACEHOLDER)
        elif ch == '&':
            result.append('&amp;')
            pos += 1
        elif ch == '<':
            result.append('&lt;')
            pos += 1
        elif ch == '>':
            result.append('&gt;')
            pos += 1
        else:
            result.append(ch)
            pos += 1

    # Close any remaining open spans (auto-reset at end of string)
    if open_spans > 0:
        result.append('</span>' * open_spans)

    return ''.join(result)


# =============================================================================
# Internal Helpers
# =============================================================================

def _extended_to_span(inner: str) -> str | None:
    """
    Convert the content inside a ``%<...>`` extended color code to an
    opening ``<span>`` tag.

    Supports three formats:

    * **Xterm-256 color number**: ``"123"`` -> ``<span class="c123">``
    * **Hex color**: ``"#FF0000"`` -> ``<span style="color:#FF0000">``
    * **Background prefix**: ``"bg123"`` or ``"bg#FF0000"`` ->
      background-color variants of the above.

    Args:
        inner: Content between ``%<`` and ``>``
               (e.g. ``"245"``, ``"#FF0000"``, ``"bg123"``).

    Returns:
        HTML ``<span>`` opening tag string, or ``None`` if *inner*
        is not a recognised color code format.
    """
    # Check for background prefix
    bg = inner.startswith('bg')
    value = inner[2:] if bg else inner

    # Hex color: #RRGGBB (exactly 7 chars including #)
    if value.startswith('#') and len(value) == 7:
        try:
            int(value[1:], 16)  # Validate hex digits
        except ValueError:
            return None
        if bg:
            return f'<span style="background-color:{value}">'
        return f'<span style="color:{value}">'

    # Xterm-256 color number: 0-255
    if value.isdigit():
        code = int(value)
        if 0 <= code <= 255:
            cls = f'bg{code}' if bg else f'c{code}'
            return f'<span class="{cls}">'

    return None
