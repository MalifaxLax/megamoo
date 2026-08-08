"""
MegaMOO Color and Text Formatting

This module is the server's colour pipeline: it converts human-friendly
colour markup in game text into ANSI escape sequences that terminal
clients can render.

Colour Systems Supported
------------------------
MegaMOO handles several colour-code dialects so that builders, verbs,
and legacy content can all produce coloured output:

1. **MOO-style basic codes** -- Single-letter codes prefixed with ``%``.
   Lowercase letters produce normal-intensity colours; uppercase letters
   produce bright/bold variants.  Examples: ``%r`` (red), ``%G`` (bright
   green), ``%n`` (reset to default).

2. **MOO-style extended codes** -- Bracket syntax ``%<...>`` supporting:
   - Xterm 256-colour palette indices: ``%<123>`` (foreground),
     ``%<bg123>`` (background).
   - Hex RGB colours: ``%<#FF0000>`` (foreground),
     ``%<bg#FF0000>`` (background).

3. **ANSI named colours** -- Curly-brace names like ``{red}``, ``{bold}``,
   ``{normal}``.  Primarily used in configuration strings.

4. **MXP colour tags** -- XML-style ``<color fore="red">text</color>``
   tags from the MXP (MUD eXtension Protocol).  Simplified support.

Architecture
------------
The module provides two main classes:

- ``ColorProcessor`` -- Converts colour codes to ANSI escapes (or strips
  them entirely for clients that do not support colour).
- ``TextFormatter`` -- Higher-level text layout utilities (wrapping,
  centering, boxing) that are colour-aware and compute visible widths by
  stripping colour codes before measuring.

A module-level singleton ``_strip_processor`` is created at import time
for internal use by ``TextFormatter``; verb code and other modules
should create their own ``ColorProcessor`` instance (or use one provided
by the session/connection layer).

Literal Percent Signs
---------------------
To output a literal ``%`` when MOO colour codes are active, use ``%%``.
The processor replaces ``%%`` with a null placeholder before scanning
for colour tokens, then restores it to ``%`` afterwards.

Copyright (c) 2026
License: MIT
"""

from typing import Dict, Optional, Tuple
import re

from .globals import SIGIL_CLASS
from enum import IntEnum
import logging

logger = logging.getLogger('megamoo.color')


# ============================================================================
# PRE-COMPILED REGEX PATTERNS
# ============================================================================
# These are compiled once at module load for performance.  Each pattern
# corresponds to one colour-code dialect.

# Matches extended MOO colour codes: %<123>, %<bg#FF0000>, etc.
_RE_MOO_EXTENDED = re.compile(SIGIL_CLASS + r'<([^>]+)>')

# Matches basic single-letter MOO colour codes: %r, %G, %n, etc.
# The negative lookahead (?![a-zA-Z]) prevents matching the first letter
# of a multi-letter sequence (e.g. "%red" should NOT match as %r + "ed").
_RE_MOO_BASIC = re.compile(SIGIL_CLASS + r'([a-zA-Z])(?![a-zA-Z])')

# Matches ANSI named colour tags: {red}, {bold}, {normal}, etc.
_RE_ANSI_NAMED = re.compile(r'\{([a-zA-Z]+)\}')

# Matches MXP colour tags: <color fore="red">text</color>
_RE_MXP_COLOR = re.compile(r'<color\s+fore="([^"]+)">([^<]+)</color>', re.IGNORECASE)

# --- Stripping patterns (same dialects, but used to *remove* codes) ---

_RE_STRIP_MOO_EXTENDED = re.compile(SIGIL_CLASS + r'<[^>]+>')
_RE_STRIP_MOO_BASIC = re.compile(SIGIL_CLASS + r'[a-zA-Z](?![a-zA-Z])')
_RE_STRIP_ANSI_NAMED = re.compile(r'\{[a-zA-Z]+\}')
# Matches raw ANSI escape sequences already in the string (ESC[...m)
_RE_STRIP_ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*m')
# Matches MXP tags, capturing inner content for preservation
_RE_STRIP_MXP = re.compile(r'<color[^>]*>([^<]+)</color>', re.IGNORECASE)


# ============================================================================
# ANSI CODE CONSTANTS
# ============================================================================

class ANSICode(IntEnum):
    """
    Numeric constants for ANSI SGR (Select Graphic Rendition) parameters.

    These values are placed between ``ESC[`` and ``m`` in an ANSI escape
    sequence.  For example, ``ESC[31m`` activates red foreground text.

    The enum is organised into four groups:

    - **Text attributes** (0-9): reset, bold, dim, italic, underline,
      blink, reverse, hidden, strikethrough.
    - **Standard foreground colours** (30-37): black through white.
    - **Standard background colours** (40-47): black through white.
    - **Bright foreground colours** (90-97): bright/bold variants of
      the standard foreground set.

    Note:
        Not all terminals support all attributes (e.g. blink, italic,
        and strikethrough are commonly unsupported in MUD clients).
    """
    # --- Text attributes ---
    RESET = 0
    BOLD = 1
    DIM = 2
    ITALIC = 3
    UNDERLINE = 4
    BLINK = 5
    REVERSE = 7
    HIDDEN = 8
    STRIKETHROUGH = 9

    # --- Standard foreground colours (30-37) ---
    FG_BLACK = 30
    FG_RED = 31
    FG_GREEN = 32
    FG_YELLOW = 33
    FG_BLUE = 34
    FG_MAGENTA = 35
    FG_CYAN = 36
    FG_WHITE = 37

    # --- Standard background colours (40-47) ---
    BG_BLACK = 40
    BG_RED = 41
    BG_GREEN = 42
    BG_YELLOW = 43
    BG_BLUE = 44
    BG_MAGENTA = 45
    BG_CYAN = 46
    BG_WHITE = 47

    # --- Bright/bold foreground colours (90-97) ---
    FG_BRIGHT_BLACK = 90
    FG_BRIGHT_RED = 91
    FG_BRIGHT_GREEN = 92
    FG_BRIGHT_YELLOW = 93
    FG_BRIGHT_BLUE = 94
    FG_BRIGHT_MAGENTA = 95
    FG_BRIGHT_CYAN = 96
    FG_BRIGHT_WHITE = 97


# ============================================================================
# MOO COLOUR CODE MAPPING
# ============================================================================
# Maps single-letter codes (used after '%') to their ANSICode values.
#
# Convention:
#   - Lowercase letter = normal-intensity colour
#   - Uppercase letter = bright/bold colour
#   - Special letters: n=reset, h=bold, u=underline, f=blink, i=reverse

MOO_COLOR_CODES = {
    # --- Normal-intensity foreground colours ---
    'x': ANSICode.FG_BLACK,
    'r': ANSICode.FG_RED,
    'g': ANSICode.FG_GREEN,
    'y': ANSICode.FG_YELLOW,
    'b': ANSICode.FG_BLUE,
    'm': ANSICode.FG_MAGENTA,
    'c': ANSICode.FG_CYAN,
    'w': ANSICode.FG_WHITE,

    # --- Bright/bold foreground colours ---
    'X': ANSICode.FG_BRIGHT_BLACK,
    'R': ANSICode.FG_BRIGHT_RED,
    'G': ANSICode.FG_BRIGHT_GREEN,
    'Y': ANSICode.FG_BRIGHT_YELLOW,
    'B': ANSICode.FG_BRIGHT_BLUE,
    'M': ANSICode.FG_BRIGHT_MAGENTA,
    'C': ANSICode.FG_BRIGHT_CYAN,
    'W': ANSICode.FG_BRIGHT_WHITE,

    # --- Special formatting codes ---
    'n': ANSICode.RESET,          # Normal/reset -- clears all attributes
    'h': ANSICode.BOLD,            # Highlight/bold
    'u': ANSICode.UNDERLINE,       # Underline
    'f': ANSICode.BLINK,           # Flash/blink (rarely supported)
    'i': ANSICode.REVERSE,         # Inverse/reverse video
}


# ============================================================================
# COLOUR PROCESSOR
# ============================================================================

class ColorProcessor:
    """
    Convert colour markup in game text to ANSI terminal escape sequences.

    This is the main class that verb code and the output pipeline use to
    transform builder-authored colour codes into sequences that a player's
    terminal can render.  It supports three input dialects (MOO, ANSI
    named, and MXP) and can either convert or strip them.

    When ``enable_color`` is ``False`` (e.g. for a client that does not
    support colour), all processing methods strip colour codes instead of
    converting them, ensuring clean plain-text output.

    Typical usage::

        processor = ColorProcessor(enable_color=True)
        output = processor.process("%rDanger!%n Safe now.", color_type='moo')
        # => "\\x1b[31mDanger!\\x1b[0m Safe now."

    Thread Safety:
        Instances are lightweight and stateless beyond the ``enable_color``
        flag, so they can be shared across coroutines safely.
    """

    def __init__(self, enable_color: bool = True):
        """
        Initialise the colour processor.

        Args:
            enable_color (bool): If ``True``, colour codes are converted
                to ANSI escape sequences.  If ``False``, colour codes are
                stripped from the text entirely.  Defaults to ``True``.
        """
        self.enable_color = enable_color

    def process(self, text: str, color_type: str = 'moo') -> str:
        """
        Process colour codes in *text* according to the specified dialect.

        This is the primary entry point.  It dispatches to the
        dialect-specific method (``process_moo_colors``,
        ``process_ansi_colors``, or ``process_mxp_colors``).  If colour
        is disabled, all codes are stripped instead.

        Args:
            text (str): Text containing colour markup.
            color_type (str): The colour-code dialect to process.
                One of ``'moo'``, ``'ansi'``, or ``'mxp'``.
                Defaults to ``'moo'``.

        Returns:
            str: Text with colour codes converted to ANSI escapes
            (or stripped, if colour is disabled).
        """
        if not self.enable_color:
            return self.strip_colors(text, color_type)

        if color_type == 'moo':
            return self.process_moo_colors(text)
        elif color_type == 'ansi':
            return self.process_ansi_colors(text)
        elif color_type == 'mxp':
            return self.process_mxp_colors(text)
        else:
            return text

    def process_moo_colors(self, text: str) -> str:
        """
        Process MOO-style colour codes and convert them to ANSI escapes.

        Handles two sub-formats:

        **Basic codes** (``%<letter>``):
            Single-letter codes looked up in ``MOO_COLOR_CODES``.
            Examples: ``%r`` (red), ``%G`` (bright green), ``%n`` (reset).

        **Extended codes** (``%<...>``):
            - Xterm 256-colour index: ``%<123>`` sets foreground to
              palette colour 123.  ``%<bg123>`` sets background.
            - Hex RGB: ``%<#FF0000>`` sets foreground to red via RGB.
              ``%<bg#FF0000>`` sets background.

        **Literal percent**:
            ``%%`` is converted to a literal ``%``.  The method uses a
            null-byte placeholder internally to prevent ``%%`` from being
            interpreted as a colour code during processing.

        Processing order:
            1. ``%%`` is replaced with a placeholder.
            2. Extended ``%<...>`` codes are resolved.
            3. Basic ``%x`` codes are resolved.
            4. The placeholder is restored to ``%``.

        Args:
            text (str): Text containing MOO colour codes.

        Returns:
            str: Text with MOO codes replaced by ANSI escape sequences.

        Examples::

            processor.process_moo_colors("This is %rred%n text")
            # => "This is \\x1b[31mred\\x1b[0m text"

            processor.process_moo_colors("%<196>bright red%n")
            # => "\\x1b[38;5;196mbright red\\x1b[0m"

            processor.process_moo_colors("%<#FF0000>red%n")
            # => "\\x1b[38;5;196mred\\x1b[0m"  (approximate)

            processor.process_moo_colors("%<bg21>blue background%n")
            # => "\\x1b[48;5;21mblue background\\x1b[0m"
        """
        # Step 1: Protect literal '%%' with a null-byte placeholder
        PLACEHOLDER = '\x00PCT\x00'
        text = text.replace('%%', PLACEHOLDER)

        # Step 2: Extended codes -- %<...>
        def replace_extended(match):
            """Callback for _RE_MOO_EXTENDED: resolve %<...> tokens."""
            inner = match.group(1)
            # Check for 'bg' prefix indicating a background colour
            bg = inner.startswith('bg')
            if bg:
                inner = inner[2:]  # strip the 'bg' prefix

            # Hex RGB: #RRGGBB (exactly 7 chars including '#')
            if inner.startswith('#') and len(inner) == 7:
                r, g, b = self.hex_to_rgb(inner)
                return self.rgb_to_ansi(r, g, b, background=bg)

            # Xterm 256-colour index: bare integer 0-255
            if inner.isdigit():
                code = int(inner)
                if 0 <= code <= 255:
                    if bg:
                        return f'\x1b[48;5;{code}m'
                    return f'\x1b[38;5;{code}m'

            # Unrecognised extended code -- return original text unchanged
            return match.group(0)

        text = _RE_MOO_EXTENDED.sub(replace_extended, text)

        # Step 3: Basic single-letter codes -- %r, %G, %n, etc.
        def replace_code(match):
            """Callback for _RE_MOO_BASIC: resolve %<letter> tokens."""
            code = match.group(1)
            if code in MOO_COLOR_CODES:
                ansi_code = MOO_COLOR_CODES[code]
                return self.ansi_escape(ansi_code)
            # Unrecognised letter -- leave as-is
            return match.group(0)

        text = _RE_MOO_BASIC.sub(replace_code, text)

        # Step 4: Restore literal '%' from placeholder
        return text.replace(PLACEHOLDER, '%')

    def process_ansi_colors(self, text: str) -> str:
        """
        Process ANSI named colour tags (``{red}``, ``{bold}``, etc.).

        Recognised names (case-insensitive):
            ``black``, ``red``, ``green``, ``yellow``, ``blue``,
            ``magenta``, ``cyan``, ``white``, ``normal`` (reset),
            ``bold``, ``underline``.

        Unrecognised names are left in the text unchanged.

        Args:
            text (str): Text containing ``{name}`` colour tags.

        Returns:
            str: Text with tags replaced by ANSI escape sequences.

        Example::

            processor.process_ansi_colors("{red}Warning!{normal}")
            # => "\\x1b[31mWarning!\\x1b[0m"
        """
        color_map = {
            'black': ANSICode.FG_BLACK,
            'red': ANSICode.FG_RED,
            'green': ANSICode.FG_GREEN,
            'yellow': ANSICode.FG_YELLOW,
            'blue': ANSICode.FG_BLUE,
            'magenta': ANSICode.FG_MAGENTA,
            'cyan': ANSICode.FG_CYAN,
            'white': ANSICode.FG_WHITE,
            'normal': ANSICode.RESET,
            'bold': ANSICode.BOLD,
            'underline': ANSICode.UNDERLINE,
        }

        def replace_code(match):
            color = match.group(1).lower()
            if color in color_map:
                return self.ansi_escape(color_map[color])
            return match.group(0)

        return _RE_ANSI_NAMED.sub(replace_code, text)

    def process_mxp_colors(self, text: str) -> str:
        """
        Process MXP (MUD eXtension Protocol) colour tags.

        Converts ``<color fore="name">text</color>`` into ANSI-coloured
        text followed by a reset.  Only the eight standard colour names
        are supported; unrecognised colours pass through the content
        text without any colour applied.

        This is a simplified implementation.  Full MXP support (with
        clickable links, gauges, etc.) would require a dedicated MXP
        protocol handler at the connection level.

        Args:
            text (str): Text containing MXP ``<color>`` tags.

        Returns:
            str: Text with MXP tags replaced by ANSI escape sequences.

        Example::

            processor.process_mxp_colors('<color fore="red">fire</color>')
            # => "\\x1b[31mfire\\x1b[0m"
        """
        def replace_tag(match):
            color = match.group(1).lower()
            content = match.group(2)

            color_map = {
                'red': ANSICode.FG_RED,
                'green': ANSICode.FG_GREEN,
                'blue': ANSICode.FG_BLUE,
                'yellow': ANSICode.FG_YELLOW,
                'magenta': ANSICode.FG_MAGENTA,
                'cyan': ANSICode.FG_CYAN,
                'white': ANSICode.FG_WHITE,
                'black': ANSICode.FG_BLACK,
            }

            if color in color_map:
                start = self.ansi_escape(color_map[color])
                end = self.ansi_escape(ANSICode.RESET)
                return f"{start}{content}{end}"
            # Unrecognised colour name -- return raw content without colour
            return content

        return _RE_MXP_COLOR.sub(replace_tag, text)

    def strip_colors(self, text: str, color_type: str = 'all') -> str:
        """
        Remove colour codes from text, leaving only visible content.

        This is used for clients that do not support colour, for
        computing visible string lengths (e.g. in ``TextFormatter``),
        and for logging where ANSI escapes would be noise.

        Args:
            text (str): Text potentially containing colour codes.
            color_type (str): Which dialect(s) to strip.  One of:
                - ``'moo'``  -- Strip MOO basic and extended codes.
                - ``'ansi'`` -- Strip ``{name}`` tags and raw ANSI
                  escape sequences.
                - ``'mxp'``  -- Strip MXP ``<color>`` tags (preserving
                  the inner text).
                - ``'all'``  -- Strip all of the above (default).

        Returns:
            str: Text with the specified colour codes removed.
        """
        if color_type in ('moo', 'all'):
            text = _RE_STRIP_MOO_EXTENDED.sub('', text)
            text = _RE_STRIP_MOO_BASIC.sub('', text)

        if color_type in ('ansi', 'all'):
            text = _RE_STRIP_ANSI_NAMED.sub('', text)
            # Also strip raw ANSI escape sequences (ESC[...m)
            text = _RE_STRIP_ANSI_ESCAPE.sub('', text)

        if color_type in ('mxp', 'all'):
            # Preserve the content inside MXP tags, strip the tags themselves
            text = _RE_STRIP_MXP.sub(r'\1', text)

        return text

    # ----------------------------------------------------------------
    # Low-level conversion helpers
    # ----------------------------------------------------------------

    @staticmethod
    def ansi_escape(code: int) -> str:
        """
        Build an ANSI SGR escape sequence from a numeric code.

        Produces the string ``ESC[<code>m`` where ESC is ``\\x1b``.

        Args:
            code (int): The SGR parameter number (e.g. 31 for red
                foreground, 0 for reset).

        Returns:
            str: The complete escape sequence string.

        Example::

            ColorProcessor.ansi_escape(31)
            # => "\\x1b[31m"
        """
        return f'\x1b[{code}m'

    @staticmethod
    def rgb_to_ansi(r: int, g: int, b: int, background: bool = False) -> str:
        """
        Convert an RGB colour to an ANSI 256-colour escape sequence.

        Uses a simplified quantisation: each channel is divided by 51
        (mapping 0-255 to 0-5) and combined into a single index in the
        xterm 6x6x6 colour cube (indices 16-231).

        Note:
            This is an approximation.  Exact RGB rendering requires
            true-colour support (``ESC[38;2;R;G;Bm``), which not all
            MUD clients implement.

        Args:
            r (int): Red channel value (0-255).
            g (int): Green channel value (0-255).
            b (int): Blue channel value (0-255).
            background (bool): If ``True``, produce a background colour
                sequence (SGR 48).  If ``False``, produce foreground
                (SGR 38).  Defaults to ``False``.

        Returns:
            str: ANSI escape sequence for the closest 256-colour match.
        """
        # Quantise each channel to 0-5 and compute the 6x6x6 cube index
        code = 16 + (36 * (r // 51)) + (6 * (g // 51)) + (b // 51)

        if background:
            return f'\x1b[48;5;{code}m'
        else:
            return f'\x1b[38;5;{code}m'

    @staticmethod
    def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
        """
        Parse a hexadecimal colour string into an (R, G, B) tuple.

        Accepts strings with or without a leading ``#``.

        Args:
            hex_color (str): Hex colour string, e.g. ``"#FF0000"`` or
                ``"FF0000"``.

        Returns:
            tuple[int, int, int]: A 3-tuple of integers in the range
            0-255 representing (red, green, blue).

        Raises:
            ValueError: If the string is not a valid 6-digit hex colour.
        """
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


# ============================================================================
# MODULE-LEVEL SINGLETON (for internal use by TextFormatter)
# ============================================================================

# A shared ColorProcessor used by TextFormatter methods to strip colour
# codes when computing visible string lengths.  External code should
# create its own instance via ``ColorProcessor(enable_color=...)``
_strip_processor = ColorProcessor()


# ============================================================================
# TEXT FORMATTER
# ============================================================================

class TextFormatter:
    """
    Format text for display with colour-aware wrapping, centering, and
    boxing.

    All methods are static and compute visible string lengths by stripping
    colour codes before measuring.  This ensures that ANSI escape
    sequences (which are invisible to the player) do not throw off
    alignment or wrapping calculations.

    These utilities are used by room descriptions, help pages, score
    boards, and any other output that needs precise layout.
    """

    @staticmethod
    def wrap_text(text: str, width: int = 78, indent: int = 0) -> str:
        """
        Word-wrap text to a maximum width, accounting for colour codes.

        Colour codes are stripped for the purpose of measuring word
        lengths, but they remain in the output.  This prevents invisible
        escape sequences from causing lines to wrap too early.

        Args:
            text (str): The text to wrap.
            width (int): Maximum visible characters per line.  Defaults
                to 78, the standard MUD display width.
            indent (int): Number of spaces to prepend to continuation
                lines (lines after the first).  Defaults to 0.

        Returns:
            str: The wrapped text with ``\\n`` line separators.
        """
        words = text.split()
        lines = []
        current_line = []
        current_length = 0
        indent_str = ' ' * indent

        for word in words:
            # Measure visible width (strip colour codes for length calc)
            word_length = len(_strip_processor.strip_colors(word))

            # Check if adding this word would exceed the line width
            # (account for spaces between words with len(current_line))
            if current_length + word_length + len(current_line) > width:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
                current_length = word_length
            else:
                current_line.append(word)
                current_length += word_length

        # Flush the last line
        if current_line:
            lines.append(' '.join(current_line))

        # Apply indentation to continuation lines
        if indent > 0 and len(lines) > 1:
            lines = [lines[0]] + [indent_str + line for line in lines[1:]]

        return '\n'.join(lines)

    @staticmethod
    def center_text(text: str, width: int = 78, fill_char: str = ' ') -> str:
        """
        Center text within a fixed width, accounting for colour codes.

        The visible length of *text* is computed after stripping colour
        codes.  Padding is applied evenly on both sides using
        *fill_char*.  If the text is already wider than *width*, it is
        returned unchanged.

        Args:
            text (str): The text to center.
            width (int): The total output width.  Defaults to 78.
            fill_char (str): The character used for padding.  Defaults
                to a space.

        Returns:
            str: The centered text, padded to *width*.
        """
        # Compute visible length without colour codes
        text_length = len(_strip_processor.strip_colors(text))
        padding = width - text_length

        if padding <= 0:
            return text

        left_padding = padding // 2
        right_padding = padding - left_padding

        return fill_char * left_padding + text + fill_char * right_padding

    @staticmethod
    def create_box(text: str, width: int = 78, style: str = 'single') -> str:
        """
        Surround text with a decorative border box.

        The box is drawn using Unicode box-drawing characters (or ASCII
        fallbacks) and spans the full *width*.  Multi-line text is
        supported; each line is individually padded to fill the box.

        Available styles:
            - ``'single'`` -- thin Unicode lines (default).
            - ``'double'`` -- double Unicode lines.
            - ``'ascii'``  -- plain ASCII (``+``, ``-``, ``|``), safe
              for all terminals.

        Args:
            text (str): The content to place inside the box.  May
                contain ``\\n`` for multiple lines.
            width (int): The outer width of the box (including borders).
                Defaults to 78.
            style (str): The border style.  Defaults to ``'single'``.

        Returns:
            str: The boxed text as a multi-line string.

        Example::

            TextFormatter.create_box("Hello!", width=30, style='ascii')
            # +----------------------------+
            # | Hello!                     |
            # +----------------------------+
        """
        # Box-drawing character sets: (top-left, horizontal, top-right,
        #                               vertical, bottom-left, bottom-right)
        box_chars = {
            'single': ('\u250c', '\u2500', '\u2510', '\u2502', '\u2514', '\u2518'),
            'double': ('\u2554', '\u2550', '\u2557', '\u2551', '\u255a', '\u255d'),
            'ascii': ('+', '-', '+', '|', '+', '+'),
        }

        chars = box_chars.get(style, box_chars['single'])
        top_left, horiz, top_right, vert, bottom_left, bottom_right = chars

        lines = text.split('\n')
        result = []

        # Top border
        result.append(top_left + horiz * (width - 2) + top_right)

        # Content lines, padded to fill the interior
        for line in lines:
            # Compute visible length for padding calculation
            line_length = len(_strip_processor.strip_colors(line))
            padding = width - line_length - 4  # subtract borders + spaces
            result.append(f"{vert} {line}{' ' * padding} {vert}")

        # Bottom border
        result.append(bottom_left + horiz * (width - 2) + bottom_right)

        return '\n'.join(result)
