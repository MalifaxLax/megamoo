"""
View help topics or get help on a specific command.

Usage: help [topic]
       help #<object>            - Show help text for an object (gm3+)
       help #<object>.<verb>     - Show help for a verb on an object (gm3+)

Examples:
    help            - List all available help topics
    help look       - Get help on the look command
    help combat     - Read about a help topic
    help #42        - Show help text for object #42
    help #42.go     - Show help for the go verb on #42
"""

help_obj = db.get_object(54)
plevel = auth_level(pobj)

if not args:
    # List all available topics
    topics = []
    for name in help_obj.properties_list(include_inherited=False, database=db):
        if name in ('name', 'cname', 'name_mod_list', 'description'):
            continue
        topics.append(name)

    # List verbs with docstrings the player can see
    verb_topics = []
    seen = set()
    # Engine machinery, not player commands: hook verbs invoked by
    # name via call_verb. They cannot be marked hidden -- that also
    # removes them from dispatch -- so help filters them here.
    _INTERNAL_EXACT = {
        'msg', 'msg_room', 'gmove', 'vmove', 'match_exit',
        'look_here', 'look_self', 'rlook', 'make_postatus',
        'get_condition', 'get_position', 'get_status',
        'hands_free', 'clear_hand', 'move_to_hand', 'time_ok',
        'postring', 'at_post_move', 'invoke', 'enter_func',
        'exit_func', 'items_on_top', 'items_under', 'do_wait',
        'do_intoxicate', 'liquid', 'list_active', 'trigger',
        'trigger_all', 'mark', 'unmark', 'dot', 'tt', 'ceat',
        'cdrink',
    }
    _INTERNAL_PREFIX = ('_', 'on_', 'in_', 'under_', 'behind_')
    # One verb implements every compass command, so deduping onto
    # names[0] would show only 'n'. List the long forms instead.
    _DIRECTION_CANON = 'n'
    _DIRECTION_SHOWN = ['north', 'south', 'east', 'west',
                        'up', 'down', 'in', 'out']
    for obj in [pobj, pobj.location] + list(pobj.location.contents):
        if not obj:
            continue
        for vname, (vdef, _) in (obj._resolved_verbs or {}).items():
            if vdef.hidden:
                continue
            if vdef.auth and plevel < vdef.auth:
                continue
            # _resolved_verbs is keyed by every legal abbreviation,
            # so dedupe on the canonical name; this also collapses
            # aliases (@set/@val -> @set).
            _names = vdef.names or [vname]
            canon = _names[0]
            if (canon in _INTERNAL_EXACT
                    or canon.startswith(_INTERNAL_PREFIX)
                    or (canon.endswith('_') and len(canon) > 1)):
                continue
            if canon in seen:
                continue
            seen.add(canon)
            code = vdef.code or ''
            if code.lstrip().startswith('"""') or code.lstrip().startswith("'''"):
                if canon not in topics:
                    if canon == _DIRECTION_CANON:
                        verb_topics.extend(_DIRECTION_SHOWN)
                    else:
                        verb_topics.append(canon)

    pobj.msg("")
    pobj.msg("&<245>Help Topics&n")
    if topics:
        pobj.msg(', '.join(sorted(topics)))
    if verb_topics:
        pobj.msg("")
        pobj.msg("&<245>Command Help&n")
        pobj.msg(', '.join(sorted(verb_topics)))
    if not topics and not verb_topics:
        pobj.msg("No help topics available.")
    return

topic = args.strip()

# 0. Object help: help #<objnum> or help #<objnum>.<verb>
if topic.startswith('#'):
    if plevel < 3:
        pobj.msg("There's no help for that.")
        return
    rest = topic[1:]
    obj_part = rest
    verb_part = None
    if '.' in rest:
        obj_part, verb_part = rest.split('.', 1)
    if not obj_part.isdigit():
        pobj.msg("There's no help for that.")
        return
    obj = db.get_object(int(obj_part))
    if not obj:
        pobj.msg("There's no help for that.")
        return
    if verb_part is not None:
        # help #obj.verb — search only this object's own verbs
        if not verb_part:
            pobj.msg("There's no help for that.")
            return
        vdef = None
        for v in obj.verbs:
            if verb_part.lower() in [n.lower() for n in v.names]:
                vdef = v
                break
        if not vdef:
            pobj.msg("There's no help for that.")
            return
        if vdef.auth and plevel < vdef.auth:
            pobj.msg("There's no help for that.")
            return
        code = vdef.code or ''
        stripped = code.lstrip()
        for quote in ('"""', "'''"):
            if stripped.startswith(quote):
                end = stripped.find(quote, len(quote))
                if end > 0:
                    docstring = stripped[len(quote):end].strip()
                    pobj.msg(f"\n&<245>#{obj_part}.{vdef.names[0]}&n")
                    pobj.msg(docstring)
                    return
        pobj.msg(f"No help available for '{verb_part}'.")
        return
    else:
        # help #obj — show object.help_text
        help_text = getattr(obj, 'help_text', None)
        if not help_text:
            pobj.msg("There's no help for that.")
            return
        pobj.msg(f"\n&<245>#{obj_part} ({obj.name})&n")
        pobj.msg(help_text)
        return

topic = topic.lower()

# 1. Check if topic matches a property name on #54
for name in help_obj.properties_list(include_inherited=False, database=db):
    if name.lower() == topic:
        val = getattr(help_obj, name, None)
        if isinstance(val, str):
            pobj.msg(f"\n&<245>{name}&n")
            pobj.msg(val)
            return
        elif isinstance(val, dict):
            pobj.msg(f"\n&<245>{name}&n")
            pobj.msg(', '.join(sorted(val.keys())))
            return

# 2. Search all dict properties on #54 for topic as a subtopic key
for name in help_obj.properties_list(include_inherited=False, database=db):
    val = getattr(help_obj, name, None)
    if isinstance(val, dict):
        for key, text in val.items():
            if key.lower() == topic:
                pobj.msg(f"\n&<245>{name} > {key}&n")
                pobj.msg(text)
                return

# 3. Check if topic matches a verb name
for obj in [pobj, pobj.location] + list(pobj.location.contents):
    if not obj:
        continue
    _, vdef = obj.find_verb(topic, db)
    if vdef:
        if vdef.auth and plevel < vdef.auth:
            break
        code = vdef.code or ''
        # Extract docstring
        stripped = code.lstrip()
        for quote in ('"""', "'''"):
            if stripped.startswith(quote):
                end = stripped.find(quote, len(quote))
                if end > 0:
                    docstring = stripped[len(quote):end].strip()
                    pobj.msg(f"\n&<245>{vdef.names[0]}&n")
                    pobj.msg(docstring)
                    return
        pobj.msg(f"No help available for '{topic}'.")
        return

pobj.msg("There's no help for that.")

