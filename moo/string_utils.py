"""
String Utilities for MegaMOO

This module provides the core text-substitution and formatting engine used
throughout the MegaMOO server.  It handles three major areas:

1. **Emit Substitution (esub)** -- Replaces placeholder tokens in message
   strings with object names.  This is the primary mechanism verbs use to
   build contextual output, e.g. ``"&S attacks &d!"`` becomes
   ``"Gandalf attacks the orc!"``.

2. **Pronoun Substitution (psub1 / psub2)** -- Resolves gendered pronoun
   tokens (``&EPS``, ``&OPO``, etc.) against one or two game objects,
   allowing gender-correct prose like ``"He draws his sword"`` or
   ``"They ready their staff"``.

3. **List / Formatting Helpers** -- Converts Python lists into
   human-readable English phrases, numbered menus, or columnar layouts
   suitable for display in a text-based MUD/MOO client.

Architecture
------------
The module exposes a single **module-level singleton** ``su``, which is the
idiomatic way to access all utilities::

    from moo.string_utils import su

    text = su.esub("You attack &d!", sub=player, dob=target)
    text = su.psub1("&CN draws &EPP sword.", eobj=player)
    english = su.listtoenglish(["a sword", "a shield", "a helm"])

This mirrors the Evennia convention of providing a lightweight, stateless
utility object that can be imported anywhere without circular-dependency
issues.

Token Reference
---------------
Emit tokens (esub):
    &s / &S   -- subject name / the same name capitalised
    &d / &D   -- direct-object name / capitalised
    &i / &I   -- indirect-object name / capitalised
    &u / &U   -- noun string (from uob) / capitalised noun
    &ps/&po/&pp/&pa/&pr -- gender pronouns resolved from the subject

Enactor pronoun tokens (psub1):
    &N / &CN             -- enactor name / capitalised
    &EPS / &EPO / &EPP / &EPR  -- enactor pronouns (subject/object/possessive/reflexive)
    &CEPS / &CEPO / &CEPP / &CEPR  -- capitalised enactor pronouns

Target pronoun tokens (psub2, in addition to psub1):
    &T / &CT             -- target name / capitalised
    &OPS / &OPO / &OPP / &OPR  -- target pronouns
    &COPS / &COPO / &COPP / &COPR  -- capitalised target pronouns

Ported from the Evennia StringUtils module.

Copyright (c) 2026
License: MIT
"""

import re
from textwrap import fill as wfill
from .globals import GENDER_PRONOUN_MAP, RE_GENDER_PRONOUN, SUBST_SIGILS


# ============================================================================
# HELPER FUNCTIONS -- safe property access and pronoun lookup
# ============================================================================

def _sub_token(text: str, letter: str, value: str) -> str:
    """
    Replace one token under every recognised sigil.

    Each token used to be spelled out twice -- ``'&d'`` and ``'$d'`` -- so
    adding a third sigil would have meant editing ten call sites and
    getting one of them wrong.  Driving it from ``SUBST_SIGILS`` means the
    set of prefixes is stated once, in globals.

    A token only counts when it is not the front of a longer word.  A
    plain ``str.replace`` had no such rule, so ``"You draw a &sword."``
    came out as ``"You draw a Gandalfword."`` -- and every literal ``&``
    followed by one of ``s S d D i I u U`` or a pronoun letter was eaten
    the same way, ``&amp;`` and ``R&D`` included.  This is the rule the
    colour codes already use for the same sigil.

    Args:
        text: The template.
        letter: The token letter, without a sigil (``'d'``, ``'S'``, ...).
        value: What to put in its place.

    Returns:
        str: The text with every ``<sigil><letter>`` replaced.
    """
    # A numeric slot also has to refuse a following digit, or `&1` would
    # bite into `&10`.  (The caller sorts high-index-first as well; belt
    # and braces, since only one of the two is obvious at a glance.)
    tail = r'(?![A-Za-z0-9])' if letter[-1].isdigit() else r'(?![A-Za-z])'
    for sigil in SUBST_SIGILS:
        # A lambda for the replacement, not the string: `value` is a
        # player-supplied name, and re.sub reads backslashes in a literal
        # replacement as group references.
        text = re.sub(re.escape(sigil + letter) + tail, lambda _: value, text)
    return text


def _has_token(text: str, letters: str) -> bool:
    """
    Whether *text* contains ``<sigil><letters>`` under any sigil.

    The fast-path guards used to test for a literal ``'&E'``.  After the
    tokens moved to ``&`` those guards were false for every converted
    string, so the substitution block beneath each one was skipped
    silently -- the text came out with ``&EPP`` still in it.  A guard that
    knows about one sigil is worse than no guard at all.

    Args:
        text: The template being substituted.
        letters: Token prefix to look for, without a sigil.

    Returns:
        bool: True if any recognised sigil is followed by *letters*.
    """
    return any(sigil + letters in text for sigil in SUBST_SIGILS)


def _getprop(obj, name, default=None):
    """
    Safely retrieve an attribute from a MegaMOO object.

    This wrapper exists because game objects may be in partially-initialised
    states (e.g. during database load) or may not have the requested
    attribute at all.  Rather than raising ``AttributeError``, we silently
    fall back to *default*.

    Args:
        obj:     The game object to inspect.
        name:    Attribute name to look up (e.g. ``'name'``, ``'noun'``).
        default: Value to return when the attribute is missing or ``None``.

    Returns:
        The attribute value, or *default* if the attribute is absent,
        ``None``, or an exception occurs during access.
    """
    try:
        val = getattr(obj, name, None)
        return val if val is not None else default
    except Exception:
        return default


def _pronoun_map(obj):
    """
    Return the pronoun dictionary for *obj* based on its ``gender`` property.

    Looks up ``obj.gender`` in the global ``GENDER_PRONOUN_MAP`` defined in
    ``moo.globals``.  If the gender is missing, ``None``, or not a
    recognised key, the ``'ambiguous'`` pronoun set is used (typically
    they/them/their).

    The returned dict maps short codes to pronoun strings::

        {'ps': 'he', 'po': 'him', 'pp': 'his', 'pa': 'his', 'pr': 'himself'}

    Args:
        obj: A MegaMOO game object with an optional ``gender`` property.

    Returns:
        dict: A mapping of pronoun-type codes (``ps``, ``po``, ``pp``,
        ``pa``, ``pr``) to the appropriate pronoun strings for this
        object's gender.
    """
    gender = _getprop(obj, 'gender', 'ambiguous')
    if gender not in GENDER_PRONOUN_MAP:
        gender = 'ambiguous'
    return GENDER_PRONOUN_MAP[gender]


# ============================================================================
# STRING UTILS CLASS
# ============================================================================

class StringUtils:
    """
    Stateless utility class providing text substitution and formatting for
    the MegaMOO server.

    All methods are pure functions that operate on their arguments and
    produce string output; no internal state is maintained between calls.
    A single module-level instance (``su``) is created at import time and
    used throughout the server.

    The class is organised into four sections:

    1. **Gender pronoun helpers** -- low-level regex callbacks for pronoun
       resolution.
    2. **Emit substitution** -- the ``esub()`` method used by the message
       system to build contextual output strings.
    3. **Pronoun substitution** -- ``psub1()`` / ``psub2()`` and their
       ``*a`` variants for one- or two-actor pronoun replacement.
    4. **Output formatting** -- list-to-English, menus, columns, and
       word-wrapping utilities.
    """

    # ----------------------------------------------------------------
    # Gender pronoun helpers
    # ----------------------------------------------------------------

    def get_pronoun(self, regex_match, source=None):
        """
        Regex callback that resolves a pronoun token to a gendered string.

        This method is designed to be passed as the *repl* argument to
        ``re.sub`` (via a lambda).  It reads the matched token (e.g.
        ``&ps``, ``&PO``), looks up the corresponding pronoun in the
        source object's gender map, and returns the correctly-cased
        result.

        Capitalisation rule:
            If the *second* character of the token is uppercase (e.g.
            ``&Ps`` or ``&PO``), the returned pronoun is capitalised.
            Otherwise it is returned in lowercase.

        Args:
            regex_match: A ``re.Match`` object from ``RE_GENDER_PRONOUN``.
                         The full match is expected to be a string like
                         ``&ps``, ``&Po``, ``&PP``, etc.
            source:      The game object whose gender determines which
                         pronoun set to use.  If ``None``, the raw token
                         is returned unchanged.

        Returns:
            str: The resolved pronoun string, e.g. ``"he"``, ``"Her"``,
            ``"their"``.
        """
        matched = regex_match.group()       # e.g. "%ps", "%PO"
        typ = matched[1:].lower()           # e.g. "ps", "po"
        pmap = _pronoun_map(source)
        pronoun = pmap.get(typ, matched)
        # Capitalise if the first letter after the sigil was uppercase.
        # capitalise(), not str.capitalize: the pronoun map holds single
        # lowercase words today, so the two agree, but capitalize()
        # lowercases the tail and would silently wreck any multi-word or
        # internally-capitalised pronoun added later.
        return self.capitalise(pronoun) if matched[1].isupper() else pronoun

    # ----------------------------------------------------------------
    # Emit substitution (used by msg / notify)
    # ----------------------------------------------------------------

    def esub(self, text, sub=None, dob=None, iob=None, uob=None, svals=None):
        """
        Emit substitution -- replace placeholder tokens in *text* with
        object names and pronouns.

        This is the workhorse method for building contextual game output.
        Verb code passes a template string and the relevant objects, and
        ``esub`` returns the final display text.

        Token replacement order:
            0. ``&0`` / ``&1`` ... ``&N`` -- raw strings from *svals*
               (each ``sN`` kwarg fills the matching ``&N`` token).
            1. ``&u`` / ``&U`` -- noun from *uob* (if provided).
            2. Gender pronouns (``&ps``, ``&po``, etc.) -- resolved from
               *sub*'s gender.
            3. ``&s`` / ``&S`` -- subject name, plain and capitalised.
            4. ``&d`` / ``&D`` -- direct-object name, plain and capitalised.
            5. ``&i`` / ``&I`` -- indirect-object name, plain and capitalised.

        The order matters: gender-pronoun tokens are processed *before*
        ``&s``/``&S`` so that a ``&s`` inside a pronoun token does not
        cause a premature replacement.

        Args:
            text (str): The template string containing tokens to replace.
                If ``None`` or not a string, it is returned unchanged.
            sub (MOOObject, optional):  Subject object. Used for ``&s``,
                ``&S``, and all gender-pronoun tokens.
            dob (MOOObject, optional):  Direct object. Used for ``&d``
                and ``&D``.
            iob (MOOObject, optional):  Indirect object. Used for ``&i``
                and ``&I``.
            uob (MOOObject, optional):  Noun object. ``&u`` and ``&U``
                are replaced with its ``noun`` property.
            svals (dict, optional):  Raw-string slots keyed ``'s0'``,
                ``'s1'``, ... -- each replaces the matching ``&N``/``$N``
                token verbatim (no object lookup; the kwarg keeps its ``s``
                prefix, the token drops it -- ``s1`` fills ``&1``).  Unlike
                &d/&i, the value is used as-is, so this is the way to splice
                plain strings.

        Returns:
            str: Text with all recognised tokens replaced. Unrecognised
            tokens are left in place.

        Examples::

            su.esub("You attack &d!", sub=player, dob=orc)
            # => "You attack the orc!"

            su.esub("&S picks up &d.", sub=player, dob=sword)
            # => "Gandalf picks up the sword."

            su.esub("&S says '&1'.", sub=player, svals={'s1': 'Hi!'})
            # => "Gandalf says 'Hi!'."  (s1 kwarg fills the &1 token)
        """
        if not text or not isinstance(text, str):
            return text

        # --- Protect a doubled sigil, the way the colour codes already do ---
        #
        # A doubled sigil is how you write a literal one: color.py hides
        # `&&` behind a placeholder before reading any code and restores a
        # single `&` at the end.  Substitution never learned the same rule,
        # and the token regex matches `&S` wherever it sits -- including on
        # the second `&` of an escaped pair -- so `&&S` came out as `&`
        # followed by a name.
        #
        # It matters wherever a verb puts a player's own words into a
        # message: `act` doubles what you type precisely so that a stray
        # `&S` stays text rather than naming somebody else inside a line
        # attributed to you, and only half that escape was being honoured.
        #
        # Restored as `&&`, not `&`: colour processing runs after this and
        # still has its own half of the escape to consume.  Undoubling here
        # would hand it a live `&<196>` instead of a literal one.
        _ESC = '\x00SIG\x00'
        text = text.replace(SUBST_SIGILS[0] * 2, _ESC)

        # --- Raw-string slots: %0 / %1 ... / %N (also $0 / $1 ... / $N) ---
        # Each `sN` value (passed straight as a kwarg, e.g. s0="txt0") replaces
        # the matching %N/$N token verbatim -- the kwarg keeps its `s` prefix,
        # the token drops it (s0 -> %0).  Higher indices first so `%1` can't
        # clobber `%10`.
        if svals:
            for _k in sorted(svals,
                             key=lambda n: int(n[1:]) if n[1:].isdigit() else 0,
                             reverse=True):
                _idx = _k[1:]                 # 's3' -> '3'
                _rep = '' if svals[_k] is None else str(svals[_k])
                for _g in SUBST_SIGILS:
                    text = text.replace(_g + _idx, _rep)

        # --- Noun object (uob) tokens: %u / %U / $u / $U ---
        if uob is not None:
            noun = _getprop(uob, 'noun', '')
            cap_noun = noun[:1].upper() + noun[1:] if noun else ''
            text = _sub_token(text, 'U', cap_noun)
            text = _sub_token(text, 'u', noun)

        # --- Subject tokens: gender pronouns first, then %s / %S / $s / $S ---
        if sub is not None:
            # Replace gender pronouns (%ps, %po, etc.) via regex
            text = RE_GENDER_PRONOUN.sub(
                lambda m: self.get_pronoun(m, source=sub), text
            )
            sname = _getprop(sub, 'name', '')
            scap = self.capitalise(sname)
            text = _sub_token(text, 's', sname)
            text = _sub_token(text, 'S', scap)

        # --- Direct object tokens: %d / %D / $d / $D ---
        if dob is not None:
            dname = _getprop(dob, 'name', '')
            dcap = self.capitalise(dname)
            text = _sub_token(text, 'd', dname)
            text = _sub_token(text, 'D', dcap)

        # --- Indirect object tokens: %i / %I / $i / $I ---
        if iob is not None:
            iname = _getprop(iob, 'name', '')
            icap = self.capitalise(iname)
            text = _sub_token(text, 'i', iname)
            text = _sub_token(text, 'I', icap)

        return text.replace(_ESC, SUBST_SIGILS[0] * 2)

    # ----------------------------------------------------------------
    # Pronoun substitution (single enactor)
    # ----------------------------------------------------------------

    def psub1(self, tstr, eobj=None):
        """
        Single-enactor pronoun substitution.

        Replaces name and pronoun tokens in *tstr* using *eobj* (the
        enactor -- typically the player performing an action).

        Supported tokens::

            &N   -> eobj.name          &CN  -> capitalised
            &EPS -> he/she/they         &CEPS -> He/She/They
            &EPO -> him/her/them        &CEPO -> Him/Her/Them
            &EPP -> his/her/their       &CEPP -> His/Her/Their
            &EPR -> himself/herself     &CEPR -> Himself/Herself

        The ``&E``-prefixed tokens use the enactor's gender to select the
        correct pronoun.  ``%CE``-prefixed tokens are the capitalised
        variants.

        Replacement order:
            Reflexive (``&EPR``) is replaced before possessive (``&EPP``)
            before objective (``&EPO``) before subjective (``&EPS``).
            This prevents shorter tokens from matching inside longer ones
            (e.g. ``&EPS`` matching the start of ``&EPSOMETHING``).

        Args:
            tstr (str): Template string with pronoun tokens.
            eobj (MOOObject, optional): The enactor object. If ``None``,
                the string is returned unchanged.

        Returns:
            str: Text with all enactor tokens replaced.

        Example::

            su.psub1("&CN draws &EPP sword.", eobj=player)
            # Male:    "Aragorn draws his sword."
            # Female:  "Arwen draws her sword."
            # Neutral: "Golem draws its sword."
        """
        if eobj is None:
            return tstr
        pmap = _pronoun_map(eobj)

        # Replace name tokens
        pstr = _sub_token(tstr, 'N', _getprop(eobj, 'name', ''))
        pstr = _sub_token(pstr, 'CN', self.capitalise(_getprop(eobj, 'name', '')))

        # Replace lowercase enactor pronouns (%EPS, %EPO, %EPP, %EPR)
        # Only scan if '%E' is present (fast-path optimisation)
        if _has_token(pstr, 'E'):
            # Order: longest tokens first to prevent partial matches
            pstr = _sub_token(pstr, 'EPR', pmap.get('pr', 'itself'))
            pstr = _sub_token(pstr, 'EPP', pmap.get('pp', 'its'))
            pstr = _sub_token(pstr, 'EPO', pmap.get('po', 'it'))
            pstr = _sub_token(pstr, 'EPS', pmap.get('ps', 'it'))

        # Replace capitalised enactor pronouns (%CEPS, %CEPO, %CEPP, %CEPR)
        if _has_token(pstr, 'CE'):
            pstr = _sub_token(pstr, 'CEPR', self.capitalise(pmap.get('pr', 'itself')))
            pstr = _sub_token(pstr, 'CEPP', self.capitalise(pmap.get('pp', 'its')))
            pstr = _sub_token(pstr, 'CEPO', self.capitalise(pmap.get('po', 'it')))
            pstr = _sub_token(pstr, 'CEPS', self.capitalise(pmap.get('ps', 'it')))
        return pstr

    def psub1a(self, tstr, eobj=None, s1='', s2='', s3=''):
        """
        Single-enactor pronoun substitution with positional arguments.

        Extends :meth:`psub1` by also replacing ``&1``, ``&2``, and
        ``&3`` with the supplied string arguments.  This is useful for
        verbs that need to insert arbitrary text alongside pronoun-
        resolved output.

        Args:
            tstr (str): Template string.
            eobj (MOOObject, optional): The enactor object.
            s1 (str): Replacement for ``&1``.
            s2 (str): Replacement for ``&2``.
            s3 (str): Replacement for ``&3``.

        Returns:
            str: Fully substituted text.

        Example::

            su.psub1a("&CN says '&1' to &2.", eobj=player,
                      s1="Hello!", s2="the crowd")
            # => "Gandalf says 'Hello!' to the crowd."
        """
        pstr = self.psub1(tstr, eobj)
        if s1:
            pstr = _sub_token(pstr, '1', s1)
        if s2:
            pstr = _sub_token(pstr, '2', s2)
        if s3:
            pstr = _sub_token(pstr, '3', s3)
        return pstr

    # ----------------------------------------------------------------
    # Pronoun substitution (enactor + target)
    # ----------------------------------------------------------------

    def psub2(self, tstr, eobj=None, tobj=None):
        """
        Two-actor pronoun substitution (enactor + target).

        First applies :meth:`psub1` for the enactor, then replaces
        target-specific tokens using *tobj*.

        Additional target tokens::

            &T   -> tobj.name          &CT  -> capitalised
            &OPS -> he/she/they         &COPS -> He/She/They
            &OPO -> him/her/them        &COPO -> Him/Her/Them
            &OPP -> his/her/their       &COPP -> His/Her/Their
            &OPR -> himself/herself     &COPR -> Himself/Herself

        The ``&O``-prefixed tokens use the **target's** gender, while
        ``&E``-prefixed tokens (handled by psub1) use the **enactor's**
        gender.

        Args:
            tstr (str): Template string with enactor and target tokens.
            eobj (MOOObject, optional): The enactor (acting) object.
            tobj (MOOObject, optional): The target object. If ``None``,
                target tokens are left unresolved.

        Returns:
            str: Fully substituted text.

        Example::

            su.psub2("&CN attacks &T and hits &OPO!", eobj=player, tobj=orc)
            # => "Gandalf attacks the orc and hits it!"
        """
        # First pass: resolve enactor tokens
        pstr = self.psub1(tstr, eobj)
        if tobj is None:
            return pstr

        tmap = _pronoun_map(tobj)

        # Replace target name tokens
        pstr = _sub_token(pstr, 'T', _getprop(tobj, 'name', ''))
        pstr = _sub_token(pstr, 'CT', self.capitalise(_getprop(tobj, 'name', '')))

        # Replace lowercase target pronouns (%OPS, %OPO, %OPP, %OPR)
        if _has_token(pstr, 'O'):
            pstr = _sub_token(pstr, 'OPR', tmap.get('pr', 'itself'))
            pstr = _sub_token(pstr, 'OPP', tmap.get('pp', 'its'))
            pstr = _sub_token(pstr, 'OPO', tmap.get('po', 'it'))
            pstr = _sub_token(pstr, 'OPS', tmap.get('ps', 'it'))

        # Replace capitalised target pronouns (%COPS, %COPO, %COPP, %COPR)
        if _has_token(pstr, 'CO'):
            pstr = _sub_token(pstr, 'COPR', self.capitalise(tmap.get('pr', 'itself')))
            pstr = _sub_token(pstr, 'COPP', self.capitalise(tmap.get('pp', 'its')))
            pstr = _sub_token(pstr, 'COPO', self.capitalise(tmap.get('po', 'it')))
            pstr = _sub_token(pstr, 'COPS', self.capitalise(tmap.get('ps', 'it')))
        return pstr

    def psub2a(self, tstr, eobj=None, tobj=None, s1='', s2='', s3=''):
        """
        Two-actor pronoun substitution with positional arguments.

        Extends :meth:`psub2` by also replacing ``&1``, ``&2``, and
        ``&3`` with the supplied string arguments.

        Args:
            tstr (str): Template string.
            eobj (MOOObject, optional): The enactor object.
            tobj (MOOObject, optional): The target object.
            s1 (str): Replacement for ``&1``.
            s2 (str): Replacement for ``&2``.
            s3 (str): Replacement for ``&3``.

        Returns:
            str: Fully substituted text.

        Example::

            su.psub2a("&CN gives &1 to &T.", eobj=player, tobj=npc,
                      s1="a golden ring")
            # => "Frodo gives a golden ring to Samwise."
        """
        pstr = self.psub2(tstr, eobj, tobj)
        if s1:
            pstr = _sub_token(pstr, '1', s1)
        if s2:
            pstr = _sub_token(pstr, '2', s2)
        if s3:
            pstr = _sub_token(pstr, '3', s3)
        return pstr

    # ----------------------------------------------------------------
    # Output formatting helpers
    # ----------------------------------------------------------------

    def msg_list(self, string, targ_list, exclude=None):
        """
        Send a message string to every object in a target list.

        This is a convenience wrapper around the ``notify`` builtin that
        handles iteration and exclusion.  Commonly used for room-wide
        messages where the acting player should be excluded.

        Args:
            string (str): The message text to send.
            targ_list (list): List of MOOObject instances to notify.
            exclude (MOOObject or list, optional): Object(s) to skip.
                Can be a single object or a list.  ``None`` means
                no exclusions.

        Example::

            su.msg_list("Gandalf leaves north.", room.contents, exclude=player)
        """
        if not isinstance(exclude, list):
            exclude = [exclude] if exclude else []
        from .builtins import notify
        for obj in targ_list:
            if obj not in exclude:
                notify(obj, string)

    def listtoenglish(self, targlist):
        """
        Join a list of strings into a natural English phrase.

        Uses commas for three or more items, ``'and'`` before the last
        item, and no Oxford comma (matching MOO convention).

        Args:
            targlist (list of str): The strings to join.

        Returns:
            str: A human-readable phrase, or an empty string for an
            empty list.

        Examples::

            su.listtoenglish(["a sword"])
            # => "a sword"

            su.listtoenglish(["a sword", "a shield"])
            # => "a sword and a shield"

            su.listtoenglish(["a sword", "a shield", "a helm"])
            # => "a sword, a shield and a helm"
        """
        length = len(targlist)
        if length > 2:
            return ', '.join(targlist[:-1]) + ' and ' + targlist[-1]
        elif length == 2:
            return ' and '.join(targlist)
        elif length == 1:
            return targlist[0]
        return ''

    def tlisttoenglish(self, targlist):
        """
        Join a list of game objects into an English phrase using their names.

        Like :meth:`listtoenglish` but extracts ``obj.name`` from each
        element first.  ``None`` entries in the list are silently skipped.

        Args:
            targlist (list of MOOObject): Objects whose names to join.

        Returns:
            str: A human-readable phrase of object names.

        Example::

            su.tlisttoenglish([sword_obj, shield_obj])
            # => "a sword and a shield"
        """
        names = [obj.name for obj in targlist if obj]
        return self.listtoenglish(names)

    def listtomenu(self, itemlist, prefix=''):
        """
        Format a list of strings as a numbered menu for display.

        Each item is numbered starting from 1, right-justified to 2
        digits, with the first letter capitalised.  Lines after the
        first are separated by newlines.

        Args:
            itemlist (list of str): Menu items. Empty/falsy entries are
                skipped.
            prefix (str, optional): String prepended before each line
                number (e.g. spaces for indentation).

        Returns:
            str: The formatted menu as a single string.

        Example::

            su.listtomenu(["pick up sword", "look around", "go north"])
            # =>  " 1. Pick up sword"
            # => "\\n 2. Look around"
            # => "\\n 3. Go north"
        """
        menu = ""
        for ind, elem in enumerate(itemlist):
            if not elem:
                continue
            # Capitalise the first letter of the item
            rname = elem[0].upper() + elem[1:]
            line = "{0}{1}{2}. {3}"
            if ind:
                # Prepend newline for all items after the first
                line = line.format('\n', prefix, str(ind + 1).rjust(2), rname)
            else:
                line = line.format('', prefix, str(ind + 1).rjust(2), rname)
            menu += line
        return menu

    def columnize(self, itemlist):
        """
        Format a list as two side-by-side numbered columns.

        The list is split in half; the first half becomes the left
        column and the second half the right column.  Each entry is
        numbered sequentially and left-justified to 20 characters.

        If the list has an odd number of items, a blank entry is
        appended to balance the columns.

        Args:
            itemlist (list of str): Items to arrange in columns.

        Returns:
            list of str: Lines of the two-column display, ready to be
            joined with newlines.

        Example::

            su.columnize(["sword", "shield", "helm", "boots"])
            # => [" 1. sword             3. helm",
            #     " 2. shield             4. boots"]
        """
        listlen = len(itemlist)
        # Build numbered labels: " 1.", " 2.", etc.
        nums = [f'{str(num).rjust(2)}.' for num in range(1, listlen + 1)]
        slist = [f'{nums[i]} {item}' for i, item in enumerate(itemlist)]
        # Pad to even length so both columns have equal rows
        if listlen % 2:
            slist.append('')
        # Split into left and right halves
        ind = int(listlen / 2 + .5)
        slist1 = slist[:ind]
        slist2 = slist[ind:]
        # Pair each left entry with its right-column counterpart
        return [f'{s.ljust(20)} {slist2[i]}' for i, s in enumerate(slist1)]

    def wrapstringlist(self, stringlist, width=79):
        """
        Word-wrap each string in a list and join with newlines.

        Uses Python's ``textwrap.fill`` for wrapping.  If any error
        occurs during wrapping (e.g. non-string elements), an empty
        string is returned.

        Args:
            stringlist (list of str): Lines to wrap.
            width (int, optional): Maximum line width. Defaults to 79,
                which is the traditional MUD terminal width.

        Returns:
            str: The wrapped and joined text, with leading/trailing
            whitespace stripped.
        """
        try:
            return '\n'.join([wfill(line, width) for line in stringlist]).strip()
        except Exception:
            return ''

    # ----------------------------------------------------------------
    # LambdaMOO $string_utils equivalents
    # ----------------------------------------------------------------
    #
    # Ported MOO code reaches for $string_utils constantly. These are the
    # verbs it uses most, as ordinary methods on su, so a port is a
    # mechanical rename:
    #
    #     $string_utils:from_list(lst, ", ")  ->  su.from_list(lst, ", ")
    #
    # They are methods rather than verbs on an object because call_verb()
    # takes an argument *string*, so a verb could not accept positional
    # arguments the way the MOO original does. A method call is both
    # faster and closer to what the MOO source looked like.
    #
    # Several of these are one-liners over the standard library. They earn
    # their place by carrying the name a MOO programmer will search for;
    # anything genuinely identical to a str method is deliberately absent.

    def english_list(self, items, none_str='nothing', and_str=' and ',
                     sep=', '):
        """
        Join *items* as an English phrase, with the separators MOO allows.

        MOO: ``$string_utils:english_list``.  Where :meth:`listtoenglish`
        is fixed to MegaMOO's house style, this takes the same arguments
        the MOO verb does, so ported call sites keep working.

        Examples::

            su.english_list(['a', 'b', 'c'])          # 'a, b and c'
            su.english_list([])                       # 'nothing'
            su.english_list(['x', 'y'], and_str=' or ')  # 'x or y'
        """
        items = [str(i) for i in items]
        if not items:
            return none_str
        if len(items) == 1:
            return items[0]
        if len(items) == 2:
            return items[0] + and_str + items[1]
        return sep.join(items[:-1]) + and_str + items[-1]

    def capitalise(self, subject):
        """
        Uppercase the first character, leave the rest alone.

        MOO: ``$string_utils:capitalize``.  Deliberately not
        ``str.capitalize``, which lowercases everything after the first
        character: it turns "an OLD sword" into "An old sword", "MacLeod"
        into "Macleod", and "O'Brien" into "O'brien".  Chargen used to
        call it and every such name arrived flattened.

        This is the engine's *only* implementation.  There were three --
        this one, a module-level ``_capitalised`` that esub called, and a
        ``capitalize_first`` builtin nothing called -- which is two more
        chances for the rule to drift than the rule deserves.

        ``None`` passes through unchanged rather than becoming the string
        ``"None"``, because the substitution code below hands it whatever
        a missing property returned.
        """
        if subject is None:
            return None
        s = str(subject)
        return s[:1].upper() + s[1:]

    #: American spelling.
    capitalize = capitalise

    def a_or_an(self, word):
        """
        The article for *word*.  MOO: ``$string_utils:a_or_an``.

        Vowel-initial words take "an".  This is the same simple rule MOO
        uses; it is wrong for "a unicorn" and "an hour", which is why the
        engine's own naming code stores the article explicitly rather than
        deriving it.
        """
        w = str(word).lstrip()
        return 'an' if w[:1].lower() in 'aeiou' else 'a'

    def ordinal(self, n):
        """
        1 -> '1st', 2 -> '2nd'.  MOO: ``$string_utils:ordinal``.

        The teens are special-cased: 11th, 12th and 13th, not 11st.
        """
        n = int(n)
        if 10 <= abs(n) % 100 <= 20:
            suffix = 'th'
        else:
            suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(abs(n) % 10, 'th')
        return f'{n}{suffix}'

    def pluralise(self, word, count=2):
        """
        Naive English pluralisation.  MOO: ``$string_utils:pluralize``.

        Handles the -y, -s/-x/-ch/-sh and default cases. Irregulars are
        not attempted: store an explicit plural on the object rather than
        expecting this to know about geese.
        """
        w = str(word)
        if int(count) == 1:
            return w
        if w.endswith('y') and w[-2:-1].lower() not in 'aeiou':
            return w[:-1] + 'ies'
        if w.endswith(('s', 'x', 'z', 'ch', 'sh')):
            return w + 'es'
        return w + 's'

    #: American spelling.
    pluralize = pluralise

    def find_prefix(self, prefix, candidates):
        """
        Index of the one candidate *prefix* matches, else -1.

        MOO: ``$string_utils:find_prefix``.  An exact match wins outright;
        otherwise a prefix must be unambiguous, so -1 means either nothing
        matched or several did.  This is the rule the MOO command parser
        uses, and the reason abbreviations behave predictably.
        """
        p = str(prefix).lower()
        cands = [str(c).lower() for c in candidates]
        if p in cands:
            return cands.index(p)
        hits = [i for i, c in enumerate(cands) if c.startswith(p)]
        return hits[0] if len(hits) == 1 else -1

    def index_delimited(self, subject, target, sep=' '):
        """
        Index of *target* among *subject* split on *sep*, else -1.

        MOO: ``$string_utils:index_delimited``.  Matches a whole field, so
        searching for 'cat' does not hit 'catalogue'.
        """
        parts = str(subject).split(sep)
        try:
            return parts.index(str(target))
        except ValueError:
            return -1

# ============================================================================
# MODULE-LEVEL SINGLETON
# ============================================================================

# The canonical way to use StringUtils throughout MegaMOO.
# Import as: ``from moo.string_utils import su``
su = StringUtils()
