"""One emit string that reads correctly to the actor and to the room.

A verb has always had to write its line twice -- ``msg`` saying "your ear"
and ``msg_room`` saying "his ear" -- with nothing checking that the two
stay in step.  The viewer-aware tokens exist so one string serves both,
which is only possible because substitution already runs once per
recipient: ``msg_room`` walks the room calling ``msg`` on each listener,
and ``notify`` hands ``esub`` the recipient as ``viewer``.

What this file pins down is the agreement rule, which is where the
subtleties are, and that the tokens that existed before are untouched.

`su` was `moo.string_utils`.  It is $string_utils in the world now, so it
arrives as a fixture from `conftest.py` -- a proxy whose attribute access is
a verb call.  The bodies below are unchanged: what was true of the module has
to stay true of the verb, and rewriting the assertions at the same time as
the code would have stopped them being evidence.
"""
from types import SimpleNamespace as NS

import pytest



def person(name='Malifax', gender='male', objnum=52, **kw):
    return NS(objnum=objnum, name=name, gender=gender, **kw)


def thing(name, article, objnum=100, **kw):
    return NS(objnum=objnum, name=name,
              name_mod_list=[article, '', '', '', ''], **kw)


# ------------------------------------------------------------------
# conjugate()
# ------------------------------------------------------------------

@pytest.mark.parametrize('bare, third', [
    ('smile', 'smiles'),
    ('dangle', 'dangles'),
    ('hang', 'hangs'),
    ('brush', 'brushes'),      # -sh
    ('fix', 'fixes'),          # -x
    ('buzz', 'buzzes'),        # -zz
    ('watch', 'watches'),      # -ch
    ('go', 'goes'),            # -o
    ('do', 'does'),            # -o, so not a table entry
    ('carry', 'carries'),      # consonant + y
    ('obey', 'obeys'),         # vowel + y stays
    ('have', 'has'),           # irregular
    ('be', 'is'),              # irregular
])
def test_third_person_singular(bare, third, su):
    assert su.conjugate(bare) == third
    assert su.conjugate(bare, plural=True) == bare


def test_case_is_preserved_through_an_irregular(su):
    """"Have" -> "has" must not lose a capital the author wrote."""
    assert su.conjugate('Have') == 'Has'


def test_an_empty_verb_is_left_alone(su):
    assert su.conjugate('') == ''


# ------------------------------------------------------------------
# takes_plural_verb()
# ------------------------------------------------------------------

def test_the_reader_takes_the_bare_form(su):
    """Second person, always: "you smile", never "you smiles"."""
    me = person()
    assert su.takes_plural_verb(me, viewer=me) is True


def test_somebody_else_takes_the_s_form(su):
    assert su.takes_plural_verb(person(), viewer=person('Bramble', objnum=7)) is False


def test_a_name_is_singular_even_for_a_they_character(su):
    """"Robin smiles", not "Robin smile".

    They/them takes the bare form behind the *pronoun* -- "they smile" --
    but not behind the name, and &y renders a name in the third person.
    Keying this on gender got it backwards every time it fired.
    """
    assert su.takes_plural_verb(person('Robin', gender='ambiguous')) is False


@pytest.mark.parametrize('article, plural', [
    ('a', False),
    ('an', False),
    ('a pair of', False),      # a pair *is* slung over your shoulder
    ('some', True),
    ('several', True),
    ('', False),               # more often proper-named than plural
])
def test_a_things_article_decides_it(article, plural, su):
    assert su.takes_plural_verb(thing('x', article)) is plural


@pytest.mark.parametrize('article, override', [('a', True), ('some', False)])
def test_an_explicit_plural_property_wins(article, override, su):
    assert su.takes_plural_verb(thing('x', article, plural=override)) is override


def test_nothing_is_singular(su):
    assert su.takes_plural_verb(None) is False


# ------------------------------------------------------------------
# The tokens, end to end
# ------------------------------------------------------------------

def test_one_string_reads_both_ways(su):
    me, them = person(), person('Bramble', 'female', objnum=7)
    text = '&Ys &v(smile) at &d.'

    assert su.esub(text, sub=me, dob=them, viewer=me) == 'You smile at Bramble.'
    assert su.esub(text, sub=me, dob=them, viewer=them) == 'Malifax smiles at Bramble.'


def test_the_verb_can_agree_with_the_item_instead(su):
    """&vd() is why sub can stay the character while the item acts.

    "&D &vd(dangle) from &yp ear" needs both: the possessive belongs to
    the wearer, the verb to the earhoop.  One &v() could not do both.
    """
    me = person()
    hoop = thing('a large gold earhoop', 'a', objnum=5066)
    text = '&D &vd(dangle) from &yp ear.'

    assert su.esub(text, sub=me, dob=hoop, viewer=me) == \
        'A large gold earhoop dangles from your ear.'
    assert su.esub(text, sub=me, dob=hoop, viewer=person('B', objnum=7)) == \
        'A large gold earhoop dangles from his ear.'


def test_a_plural_item_agrees_plurally(su):
    me = person()
    drapes = thing('some drapes', 'some', objnum=5035)

    assert su.esub('&D &vd(hang) there.', sub=me, dob=drapes, viewer=me) == \
        'Some drapes hang there.'


@pytest.mark.parametrize('token, mine, theirs', [
    ('&ys', 'you', 'Malifax'),
    ('&yo', 'you', 'him'),
    ('&yp', 'your', 'his'),
    ('&ya', 'yours', 'his'),
    ('&yr', 'yourself', 'himself'),
    ('&Ys', 'You', 'Malifax'),
    ('&Yo', 'You', 'Him'),
    ('&Yp', 'Your', 'His'),
    ('&Ya', 'Yours', 'His'),
    ('&Yr', 'Yourself', 'Himself'),
])
def test_each_viewer_aware_token(token, mine, theirs, su):
    me = person()
    other = person('Bramble', 'female', objnum=7)

    assert su.esub(token, sub=me, viewer=me) == mine
    assert su.esub(token, sub=me, viewer=other) == theirs


def test_the_whole_family_mirrors_the_pronoun_tokens(su):
    """&ys sits beside &ps, case for case, so there is one thing to learn.

    Also the boundary check: five two-letter tokens sharing a first
    letter, none of which may be read as a prefix of another.
    """
    me = person()
    other = person('Bramble', 'female', objnum=7)

    assert su.esub('&ys &yo &yp &ya &yr', sub=me, viewer=me) == \
        'you you your yours yourself'
    assert su.esub('&ys &yo &yp &ya &yr', sub=me, viewer=other) == \
        'Malifax him his his himself'


def test_no_viewer_reads_as_third_person(su):
    """Callers that never pass one -- most of the engine -- are unaffected."""
    assert su.esub('&Ys &v(smile).', sub=person()) == 'Malifax smiles.'


# ------------------------------------------------------------------
# Three audiences: the &t family
# ------------------------------------------------------------------

def test_one_string_serves_all_three_points_of_view(su):
    """An emit has three readers, and a combat line needs all of them.

    "You attack Bramble" / "Malifax attacks you" / "Malifax attacks
    Bramble" used to be three strings a verb wrote and kept in step by
    hand.  The verb agrees correctly in the middle row because the
    conjugator keys on `viewer is sub`, not on who is reading.
    """
    A = person('Malifax', 'male', objnum=52)
    B = person('Bramble', 'female', objnum=7)
    C = person('a bystander', 'neutral', objnum=9)
    text = '&Ys &v(attack) &to.'

    assert su.esub(text, sub=A, dob=B, viewer=A) == 'You attack Bramble.'
    assert su.esub(text, sub=A, dob=B, viewer=B) == 'Malifax attacks you.'
    assert su.esub(text, sub=A, dob=B, viewer=C) == 'Malifax attacks Bramble.'


def test_the_targets_possessive_follows_the_reader(su):
    A = person('Malifax', 'male', objnum=52)
    B = person('Bramble', 'female', objnum=7)
    C = person('a bystander', 'neutral', objnum=9)
    text = '&Ys &v(take) &tp sword.'

    assert su.esub(text, sub=A, dob=B, viewer=A) == 'You take her sword.'
    assert su.esub(text, sub=A, dob=B, viewer=B) == 'Malifax takes your sword.'
    assert su.esub(text, sub=A, dob=B, viewer=C) == 'Malifax takes her sword.'


@pytest.mark.parametrize('token, target_reads, others_read', [
    ('&ts', 'you', 'Bramble'),
    ('&to', 'you', 'Bramble'),
    ('&tp', 'your', 'her'),
    ('&ta', 'yours', 'hers'),
    ('&tr', 'yourself', 'herself'),
    ('&Ts', 'You', 'Bramble'),
    ('&Tp', 'Your', 'Her'),
    ('&Tr', 'Yourself', 'Herself'),
])
def test_each_target_token(token, target_reads, others_read, su):
    A = person('Malifax', 'male', objnum=52)
    B = person('Bramble', 'female', objnum=7)
    C = person('a bystander', 'neutral', objnum=9)

    assert su.esub(token, sub=A, dob=B, viewer=B) == target_reads
    assert su.esub(token, sub=A, dob=B, viewer=C) == others_read


def test_the_subject_takes_a_pronoun_in_object_position_but_the_target_a_name(su):
    """The one place the two families deliberately differ.

    &yo reads "him" because &ys has just said the name in the same
    sentence.  &to reads the name because nothing has named the target
    yet -- "Malifax attacks her" arriving cold names nobody.
    """
    A = person('Malifax', 'male', objnum=52)
    B = person('Bramble', 'female', objnum=7)
    C = person('a bystander', 'neutral', objnum=9)

    assert su.esub('&yo', sub=A, dob=B, viewer=C) == 'him'
    assert su.esub('&to', sub=A, dob=B, viewer=C) == 'Bramble'


def test_a_line_with_no_target_is_unaffected(su):
    """dob is optional; the &t family simply does not fire without one."""
    assert su.esub('&Ys &v(smile).', sub=person(), viewer=None) == 'Malifax smiles.'


@pytest.mark.parametrize('text, expected', [
    ('&S says hello to &d.', 'Malifax says hello to Bramble.'),
    ('&S draws &pp sword.', 'Malifax draws his sword.'),
    ('&s and &d', 'Malifax and Bramble'),
])
def test_the_old_tokens_are_untouched(text, expected, su):
    """Adoption is opt-in: new letters, so nothing already written moves."""
    me, them = person(), person('Bramble', 'female', objnum=7)
    assert su.esub(text, sub=me, dob=them, viewer=me) == expected


def test_the_empty_word_takes_a(su):
    """`'' in 'aeiou'` is True -- the empty string is a substring of every
    string -- so the slice that was chosen to survive an empty word survived
    it by answering wrongly.  Found by tools/equivalence.py, comparing the
    Python against a straightforward in-game port."""
    assert su.a_or_an('') == 'a'
    assert su.a_or_an('   ') == 'a'
    assert su.a_or_an(None) == 'a'      # str(None) -> 'None'


def test_a_or_an_still_uses_the_simple_vowel_rule(su):
    """Deliberately wrong for 'hour' and 'unicorn'; the naming code stores the
    article explicitly rather than deriving it.  Pinned so a well-meaning fix
    does not quietly change what every ported MOO verb expects."""
    assert su.a_or_an('hour') == 'a'
    assert su.a_or_an('unicorn') == 'an'
    assert su.a_or_an('apple') == 'an'
    assert su.a_or_an('sword') == 'a'
