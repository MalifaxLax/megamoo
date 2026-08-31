"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

from moo.globals import GENDER_PRONOUN_MAP, RE_GENDER_PRONOUN, SUBST_SIGILS

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

def _has_family_token(text: str, prefix: str) -> bool:
    """Whether *text* carries a viewer-aware token of *prefix*'s family.

    A cheap guard, so the overwhelmingly common emit that uses none of
    them does no work at all.
    """
    lower, upper = prefix, prefix.upper()
    return any(sig + lower in text or sig + upper in text
               for sig in SUBST_SIGILS)

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

def _same_object(a, b):
    """Whether two references name the same object, by number."""
    if a is None or b is None:
        return False
    an, bn = getattr(a, 'objnum', None), getattr(b, 'objnum', None)
    return an is not None and an == bn

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
    tail = r'(?![A-Za-z0-9])' if letter[-1].isdigit() else r'(?![A-Za-z])'
    for sigil in SUBST_SIGILS:
        text = re.sub(re.escape(sigil + letter) + tail, lambda _: value, text)
    return text

import re

def esub(text, sub=None, dob=None, iob=None, uob=None,
             svals=None, viewer=None):
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

        _ESC = '\x00SIG\x00'
        text = text.replace(SUBST_SIGILS[0] * 2, _ESC)

        if svals:
            for _k in sorted(svals,
                             key=lambda n: int(n[1:]) if n[1:].isdigit() else 0,
                             reverse=True):
                _idx = _k[1:]
                _rep = '' if svals[_k] is None else str(svals[_k])
                for _g in SUBST_SIGILS:
                    text = text.replace(_g + _idx, _rep)

        if uob is not None:
            noun = _getprop(uob, 'noun', '')
            cap_noun = noun[:1].upper() + noun[1:] if noun else ''
            text = _sub_token(text, 'U', cap_noun)
            text = _sub_token(text, 'u', noun)

        def _protect(value):
            """Keep a substituted name from being read as tokens itthis.

            Names go in over three passes -- subject, then direct object,
            then indirect -- and each pass rescans the whole string. So a
            name containing a sigil was substituted *again* by a later
            pass: an object called "a &d" inserted at the subject step had
            its "&d" replaced by the direct object's name at the next one,
            and a name carrying "&<196>" put a colour code into a line
            that never asked for one.

            Neutralised with the escape this function already uses for a
            deliberately doubled sigil, so the marker is turned back on
            the way out and the name displays as it was written.

            Names only. The %N raw-string slots are left alone: callers
            there are documented as escaping their own values, and doing
            it twice would show the doubling.
            """
            return value.replace(SUBST_SIGILS[0], _ESC) if value else value

        if sub is not None:
            text = RE_GENDER_PRONOUN.sub(
                lambda m: call_verb(this, 'get_pronoun', m, source=sub), text
            )
            sname = _getprop(sub, 'name', '')
            scap = call_verb(this, 'capitalise', sname)
            text = _sub_token(text, 's', _protect(sname))
            text = _sub_token(text, 'S', _protect(scap))

        if dob is not None:
            dname = _getprop(dob, 'name', '')
            dcap = call_verb(this, 'capitalise', dname)
            text = _sub_token(text, 'd', _protect(dname))
            text = _sub_token(text, 'D', _protect(dcap))

        if iob is not None:
            iname = _getprop(iob, 'name', '')
            icap = call_verb(this, 'capitalise', iname)
            text = _sub_token(text, 'i', _protect(iname))
            text = _sub_token(text, 'I', _protect(icap))

        for _who, _prefix in ((sub, 'y'), (dob, 't')):
            if _who is None or not _has_family_token(text, _prefix):
                continue
            if _same_object(_who, viewer):
                _vals = {'s': 'you', 'o': 'you', 'p': 'your',
                         'a': 'yours', 'r': 'yourself'}
                if _prefix == 'y':
                    _vals['o'] = 'you'
            else:
                _pm = _pronoun_map(_who)
                _name = _getprop(_who, 'name', '')
                _vals = {'s': _name,
                         'o': _pm['po'] if _prefix == 'y' else _name,
                         'p': _pm['pp'], 'a': _pm['pa'], 'r': _pm['pr']}
            for _case, _v in _vals.items():
                _tok = _prefix + _case
                text = _sub_token(text, _prefix.upper() + _case,
                                  _protect(call_verb(this, 'capitalise', _v)))
                text = _sub_token(text, _tok, _protect(_v))

        for _sigil in SUBST_SIGILS:
            for _name, _agrees_with in (('vd', dob), ('v', sub)):
                _plural = call_verb(this, 'takes_plural_verb', _agrees_with, viewer)
                text = re.sub(
                    re.escape(_sigil + _name) + r'\(([^)]*)\)',
                    lambda m, p=_plural: call_verb(this, 'conjugate', m.group(1), p),
                    text)

        return text.replace(_ESC, SUBST_SIGILS[0] * 2)

_a = kwargs.pop('_pyargs', None)

return esub(*(_a if _a is not None else argv), **kwargs)
