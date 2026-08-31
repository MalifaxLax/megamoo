"""
go_ verb for the chargen arch (#43) in room #42.

Runs character generation when a player enters the arch. Uses yield for
each interactive step. Returns True to prevent normal exit movement.

#43 is the arch exit. #29 is the isolation container (parented to #1,
no verbs) — pobj is moved into #29 for the duration of chargen, then
moved back to room #42 when done or cancelled.

Character is created immediately at slot selection. Each step writes its
data directly to the character object; resume is handled by reading
chargen_step from the character.

The shipped flow is deliberately minimal — slot, first name, last name,
gender — and then finalizes. It is meant as a working skeleton for a new
game to extend: add your own steps between gender and finalize, writing
each answer to the character and advancing chargen_step so resume keeps
working.

Players type 'quit' at any prompt to cancel (character is preserved for resume).

Called from the go verb via call_verb(exit, 'go_').

Hidden:  yes
Perms:   rxd
"""

import re

class _Quit(Exception):
    pass

def _header(text):
    if (pobj.settings or {}).get('screenreader', False):
        pobj.msg(text)
        return
    border = "=" * len(text)
    pobj.msg(f"&<245>{border}&n")
    pobj.msg(text)
    pobj.msg(f"&<245>{border}&n")

def _input(prompt):
    """Yield for input. Raises _Quit if the player types 'quit'.

    The whole word, not a prefix of it. This used to accept anything
    `'quit'.startswith(ans)` matched, so answering the *name* prompt with
    "Q", "Qu" or "Qui" silently abandoned chargen -- no message, back in the
    Drop Zone, and the half-made character still holding its slot. Those are
    plausible names, and a name prompt should not have control words in it.
    """
    response = yield (prompt or "")
    if response.strip().lower() == 'quit':
        raise _Quit()
    return response

def _pick(prompt, options, allow_back=True, redisplay=None):
    """Yield until the player picks a valid numbered option or name prefix.
    Returns (index, value) or None if 'back'.
    redisplay is an optional callable that re-shows the header and menu."""
    while True:
        choice = yield from _input("&<255>>&n ")
        choice = choice.strip().lower()
        if not choice:
            continue
        if allow_back and 'back'.startswith(choice):
            return None
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                return (idx, options[idx])
        else:
            matches = []
            for i, opt in enumerate(options):
                name = str(opt).lower() if opt is not None else ''
                if name and name.startswith(choice):
                    matches.append((i, opt))
            if len(matches) == 1:
                return matches[0]
        pobj.msg("")
        pobj.msg("&<245>Try again...&n")
        pobj.msg("")
        if redisplay:
            redisplay()

def _set(obj, prop, value):
    """Set a property on obj, creating it if it doesn't exist."""
    try:
        obj.set_property(prop, value)
    except Exception:
        obj.add_property(prop, value)

def _validate_name(name, label):
    """Shared name rules. Returns an error string, or None if the name is ok."""
    if len(name) < 3:
        return "Too short. Must be at least 3 characters."
    if len(name) > 16:
        return "Too long. Must be 16 or fewer characters."
    if not name[0].isalpha():
        return "Must start with a letter."
    if not re.match(r"^[A-Za-z'-]+$", name):
        return "Only letters, apostrophes, and hyphens allowed."
    badnames = list(this.bad_names or [])
    if name.lower() in [b.lower() for b in badnames]:
        return "I don't think so."
    return None

origin_room = pobj.location
msg_room(origin_room, f"{pobj.name} is consumed by a burst of primal energy.", exclude=[pobj], sub=pobj, dob=dobj, iob=iobj)
move(pobj, db.get_object(29))

chargen_state = {'ichar': None}

def _run_chargen():
    """Inner generator containing all chargen steps."""

    ichar = None
    step = None

    first_name = None
    last_name = None
    gender = None

    _STEPS = frozenset({None, 'first_name', 'last_name', 'gender'})
    while step in _STEPS:

        while step is None:
            max_chars = this.max_characters or 5

            while True:
                characters = list(pobj.characters or [])

                slots = list(characters) + [None] * (max_chars - len(characters))
                slots = slots[:max_chars]

                _header("Which slot would you like to use? [Q]uit or [B]ack any time.")
                for i, cnum in enumerate(slots, 1):
                    if cnum:
                        try:
                            c = db.get_object(cnum)
                            display_name = c.noun or (c.name or '<unnamed>').split()[0]
                            pobj.msg(f"&<245>{i:>2}:&n {display_name}")
                        except Exception:
                            pobj.msg(f"&<245>{i:>2}:&n <invalid>")
                    else:
                        pobj.msg(f"&<245>{i:>2}:&n <unused>")

                result = yield from _pick("", slots, allow_back=False)
                if result is None:
                    continue
                slot_idx, slot_val = result

                if slot_val is not None:
                    try:
                        ichar = db.get_object(slot_val)
                        char_name = ichar.noun or (ichar.name or '<unnamed>').split()[0]
                    except Exception:
                        characters = [c for c in characters if c != slot_val]
                        pobj.characters = characters
                        pobj._mark_modified()
                        pobj.msg("  Cleared invalid slot.")
                        continue

                    chargen_step_val = ichar.chargen_step

                    if chargen_step_val is not None:
                        _header("[R]esume or [S]tart over?")
                        chose_resume = False
                        while True:
                            ans = yield from _input("&<255>>&n ")
                            ans = ans.strip().lower()
                            if not ans:
                                continue
                            if 'resume'.startswith(ans):
                                chose_resume = True
                                break
                            if 'start'.startswith(ans):
                                break
                            pobj.msg("")
                            pobj.msg("&<245>Try again...&n")
                            pobj.msg("")
                            _header("[R]esume or [S]tart over?")

                        if chose_resume:
                            chargen_state['ichar'] = ichar
                            step = chargen_step_val

                            first_name = ichar.name or ichar.noun or 'unnamed'
                            last_name = ichar.last_name
                            gender = ichar.gender

                            break

                    warn = "DESTROYING YOUR CHARACTER IS IRREVOCABLE!"
                    if (pobj.settings or {}).get('screenreader', False):
                        pobj.msg(warn)
                    else:
                        border = "=" * len(warn)
                        pobj.msg(f"&<245>{border}&n")
                        pobj.msg(f"&<245>DESTROYING YOUR CHARACTER IS &<196>IRREVOCABLE!&n")
                        pobj.msg(f"&<245>{border}&n")
                    confirm_str = f"DESTROY {char_name.upper()}"
                    pobj.msg(f"Enter &<196>{confirm_str}&n to erase {char_name}. Anything else to abort.")
                    ans = yield from _input("&<255>>&n ")
                    if ans.strip().upper() == confirm_str:
                        pobj.msg("")
                        pobj.msg(f"  Are you sure you want to destroy {char_name}? &<255>(y/n)&n")
                        ans2 = yield from _input("&<255>>&n ")
                        if not ans2.strip().lower().startswith('y'):
                            pobj.msg("")
                            pobj.msg("  Aborted.")
                            pobj.msg("")
                            ichar = None
                            continue
                        characters = [c for c in characters if c != slot_val]
                        pobj.characters = characters
                        pobj._mark_modified()
                        taken_names = list(this.character_names or [])
                        if char_name in taken_names:
                            taken_names.remove(char_name)
                            _set(this, 'character_names', taken_names)
                        recycle(ichar)
                        pobj.msg("")
                        pobj.msg(f"  &<245>A moment of silence for {char_name}...&n")
                        yield 2
                        pobj.msg("")
                    ichar = None
                    continue
                else:
                    new_char = create(parent=5, owner=pobj.objnum)
                    new_char.owner = new_char.objnum
                    new_char.noun = "unnamed"
                    new_char.add_property('name', 'unnamed')
                    new_char.add_property('account', pobj.objnum)
                    new_char.add_property('chargen_step', 'first_name')

                    chars = list(pobj.characters or [])
                    chars.append(new_char.objnum)
                    pobj.characters = chars
                    pobj._mark_modified()

                    acct_auth = list(pobj.auth or [])
                    if acct_auth:
                        new_char.add_property('auth', list(acct_auth))
                        if pobj.is_programmer:
                            new_char.flags |= 2
                        if pobj.is_wizard:
                            new_char.flags |= 4

                    ichar = new_char
                    chargen_state['ichar'] = ichar
                    step = 'first_name'
                    break

        while step == 'first_name':
            _header("What is your first name?")
            while True:
                name = yield from _input("&<255>>&n ")
                name = name.strip()
                if name.lower() == 'back':
                    step = None
                    break
                if not name:
                    continue
                err = _validate_name(name, 'first')
                if err:
                    pobj.msg(err)
                    _header("What is your first name?")
                    continue
                taken_names = list(this.character_names or [])
                first_name = su.capitalise(name)
                if first_name.lower() in [t.lower() for t in taken_names]:
                    pobj.msg("That name is taken.")
                    continue
                ichar.noun = first_name
                _set(ichar, 'name', first_name)
                taken_names.append(first_name)
                _set(this, 'character_names', taken_names)
                _set(ichar, 'chargen_step', 'last_name')
                step = 'last_name'
                break

        while step == 'last_name':
            _header("And what shall your last name be?")
            while True:
                name = yield from _input("&<255>>&n ")
                name = name.strip()
                if name.lower() == 'back':
                    step = 'first_name'
                    _set(ichar, 'chargen_step', 'first_name')
                    break
                if not name:
                    continue
                err = _validate_name(name, 'last')
                if err:
                    pobj.msg(err)
                    _header("And what shall your last name be?")
                    continue
                last_name = su.capitalise(name)
                _set(ichar, 'last_name', last_name)
                _set(ichar, 'chargen_step', 'gender')
                step = 'gender'
                break

        while step == 'gender':
            _header("[M]ale or [F]emale? (Contact a GM if you'd like other gender pronouns.)")
            while True:
                ans = yield from _input("&<255>>&n ")
                ans = ans.strip().lower()
                if not ans:
                    continue
                if 'back'.startswith(ans):
                    step = 'last_name'
                    _set(ichar, 'chargen_step', 'last_name')
                    break
                if 'male'.startswith(ans):
                    gender = 'male'
                elif 'female'.startswith(ans):
                    gender = 'female'
                else:
                    pobj.msg("")
                    pobj.msg("&<245>Try again...&n")
                    pobj.msg("")
                    _header("[M]ale or [F]emale? (Contact a GM if you'd like other gender pronouns.)")
                    continue
                _set(ichar, 'gender', gender)
                _set(ichar, 'chargen_step', 'finalize')
                step = 'finalize'
                break
            continue

    if step == 'finalize':
        pronoun = 'man' if gender == 'male' else 'woman'
        _set(ichar, 'desclist', [f"{first_name} {last_name} is an unremarkable {pronoun}."])

        _set(ichar, 'last_location', 0)

        _status = dict(ichar.status or {})
        _status['life'] = 1
        _set(ichar, 'status', _status)
        _set(ichar, 'rt', 0)

        _set(ichar, 'chargen_step', None)

        pobj.msg("")
        _header(f"{first_name} {last_name} is ready.")
        pobj.msg("Head south and step through the portal to enter the game.")
        pobj.msg("")

try:
    yield from _run_chargen()
except _Quit:
    pass
finally:
    if pobj.location and pobj.location.objnum == 29:
        move(pobj, origin_room)
        msg_room(origin_room, f"{pobj.name} arrives, looking slightly bewildered.", exclude=[pobj], sub=pobj, dob=dobj, iob=iobj)

return True
