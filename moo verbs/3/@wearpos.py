"""
Views or sets wear position data on wearable items. With no argument,
lists all 47 body positions with their numeric IDs. With an item, shows
the item's current wear_pos settings. With item = list, sets wear_pos.

Usage: @wearpos
       @wearpos <item>
       @wearpos <item> = <pos_list>

Arguments:
    item      - A wearable object (matched in room and inventory).
    pos_list  - A list of [position, layer] pairs (Python list syntax).

Auth: gm2+ (auth_level 2)

Note: Each wear entry is [pos, layer]. Positions >= 100 are L/R pairs:
base = pos % 100 corresponds to the right side, base - 1 to the left.
Example: [[140, 2]] covers both l ankle (39) and r ankle (40).
"""
if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return

positions = {
    0: 'tattoos/scars',
    1: 'head', 2: 'nose', 3: 'l eye', 4: 'r eye', 5: 'mouth', 6: 'chin',
    7: 'throat', 8: 'u neck', 9: 'nape of neck',
    10: 'chest', 11: 'l shoulder', 12: 'r shoulder', 13: 'u back', 14: 'midriff',
    15: 'l up arm', 16: 'r up arm', 17: 'l elbow', 18: 'r elbow',
    19: 'l forearm', 20: 'r forearm', 21: 'l wrist', 22: 'r wrist',
    23: 'l hand', 24: 'r hand',
    25: 'small of back', 26: 'waist', 27: 'abdomen', 28: 'lower back',
    29: 'l hip', 30: 'r hip', 31: 'pelvis', 32: 'buttocks',
    33: 'l thigh', 34: 'r thigh', 35: 'l knee', 36: 'r knee',
    37: 'l calf', 38: 'r calf', 39: 'l ankle', 40: 'r ankle',
    41: 'l foot', 42: 'r foot', 43: 'l fingers', 44: 'r fingers',
    45: 'l toes', 46: 'r toes',
}

def pos_label(pos):
    if pos >= 100:
        base = pos % 100
        r_name = positions.get(base, '???')
        l_name = positions.get(base - 1, '???')
        return '%s/%s (L/R)' % (l_name, r_name)
    return positions.get(pos, '???')

def valid_pos(pos):
    if pos in positions:
        return True
    if pos >= 100 and (pos % 100) in positions:
        return True
    return False

if 'flex' in switches:
    spec = (dobj if dobj else args).strip() if (dobj or args) else ''
    if '.' not in spec:
        pobj.msg('Usage: @wearpos/flex <object>.<pos1>,<pos2>,...')
        return
    obj_str, pos_str = spec.rsplit('.', 1)
    candidates = list(pobj.contents) + list(pobj.location.contents)
    target = bmatch(obj_str.strip(), pobj, candidates, db)
    if not target:
        pobj.msg("I don't see '%s' here." % obj_str)
        return
    wear_pos = target.wear_pos or []
    if not wear_pos:
        pobj.msg("%s has no wear positions." % target.name)
        return
    try:
        positions_to_flex = [int(x.strip()) for x in pos_str.split(',')]
    except ValueError:
        pobj.msg("Positions must be integers: @wearpos/flex anklet.39,40")
        return
    # Build valid positions including L/R expansion
    # e.g. entry [140, 2] covers 140 (pair), 40 (right), 39 (left)
    valid_positions = set()
    pos_to_entry = {}  # maps individual pos -> wear_pos entry pos
    for entry in wear_pos:
        p = entry[0]
        valid_positions.add(p)
        pos_to_entry[p] = p
        if p >= 100:
            r = p % 100
            l = r - 1
            valid_positions.add(r)
            valid_positions.add(l)
            pos_to_entry[r] = p
            pos_to_entry[l] = p
    bad = [p for p in positions_to_flex if p not in valid_positions]
    if bad:
        pobj.msg("Position(s) not on this item: %s" % ', '.join(str(b) for b in bad))
        return
    layer_flex = target.layer_flex or {}
    if not isinstance(layer_flex, dict):
        layer_flex = {}
    # Normalize string keys from JSON to ints
    layer_flex = {int(k): v for k, v in layer_flex.items()}
    changed_entries = set()
    toggled_on = 0
    toggled_off = 0
    for p in positions_to_flex:
        entry_pos = pos_to_entry[p]
        # Expand L/R pair to both resolved positions
        if p >= 100:
            r = p % 100
            resolved = [r, r - 1]
        else:
            resolved = [p]
        # Clean up old entry-pos format key if present
        if entry_pos >= 100 and entry_pos in layer_flex:
            layer_flex.pop(entry_pos)
        # Toggle based on current state of first resolved position
        is_on = layer_flex.get(resolved[0], False)
        for rp in resolved:
            if is_on:
                layer_flex.pop(rp, None)
            else:
                layer_flex[rp] = True
        changed_entries.add(entry_pos)
        if is_on:
            toggled_off += len(resolved)
        else:
            toggled_on += len(resolved)
    try:
        target.set_property('layer_flex', layer_flex)
    except KeyError:
        target.add_property('layer_flex', layer_flex, perms='rc')
    target._mark_modified()
    if toggled_on and toggled_off:
        state = f'on at {toggled_on}, off at {toggled_off}'
    elif toggled_on:
        state = f'on at {toggled_on}'
    else:
        state = f'off at {toggled_off}'
    pobj.msg(f"Toggled &<245>#{target.objnum}:{target.name}&n's layer_flex {state} position(s).")
    for ps in wear_pos:
        p = ps[0]
        if p >= 100:
            r = p % 100
            l = r - 1
            changed = p in changed_entries
            for rp in [l, r]:
                flex = layer_flex.get(rp, False)
                flex_str = ' [flex]' if flex else ''
                name = positions.get(rp, '???')
                line = '  %3d  %-20s  layer %d%s' % (rp, name, ps[1], flex_str)
                if changed:
                    pobj.msg(f'&<245>{line}&n')
                else:
                    pobj.msg(line)
        else:
            flex = layer_flex.get(p, False)
            flex_str = ' [flex]' if flex else ''
            line = '  %3d  %-20s  layer %d%s' % (p, pos_label(p), ps[1], flex_str)
            if p in changed_entries:
                pobj.msg(f'&<245>{line}&n')
            else:
                pobj.msg(line)
    return

if 'layer' in switches:
    if not dobj or prep != '=' or not iobj:
        pobj.msg('Usage: @wearpos/layer <object>[.<pos1>,<pos2>,...] = <new_layer>')
        pobj.msg('Omit positions to set all.')
        return
    try:
        new_layer = int(iobj.strip())
    except ValueError:
        pobj.msg("Layer must be an integer.")
        return
    obj_str = dobj.strip()
    target_positions = None
    if '.' in obj_str:
        obj_str, pos_str = obj_str.rsplit('.', 1)
        try:
            target_positions = [int(x.strip()) for x in pos_str.split(',')]
        except ValueError:
            pobj.msg("Positions must be integers: @wearpos/layer anklet.39,40 = 2")
            return
    candidates = list(pobj.contents) + list(pobj.location.contents)
    target = bmatch(obj_str.strip(), pobj, candidates, db)
    if not target:
        pobj.msg("I don't see '%s' here." % obj_str)
        return
    wear_pos = target.wear_pos or []
    if not wear_pos:
        pobj.msg("%s has no wear positions." % target.name)
        return
    # Build L/R expansion map
    pos_to_entry = {}
    for entry in wear_pos:
        p = entry[0]
        pos_to_entry[p] = p
        if p >= 100:
            r = p % 100
            pos_to_entry[r] = p
            pos_to_entry[r - 1] = p
    changed_positions = set()
    if target_positions is not None:
        bad = [p for p in target_positions if p not in pos_to_entry]
        if bad:
            pobj.msg("Position(s) not on this item: %s" % ', '.join(str(b) for b in bad))
            return
        entry_positions = {pos_to_entry[p] for p in target_positions}
        for entry in wear_pos:
            if entry[0] in entry_positions:
                entry[1] = new_layer
                changed_positions.add(entry[0])
    else:
        for entry in wear_pos:
            entry[1] = new_layer
            changed_positions.add(entry[0])
    target.wear_pos = wear_pos
    target._mark_modified()
    pobj.msg(f'Updated {len(changed_positions)} position(s) on &<245>#{target.objnum}:{target.name}&n:')
    for ps in wear_pos:
        line = '  %3d  %-20s  layer %d' % (ps[0], pos_label(ps[0]), ps[1])
        if ps[0] in changed_positions:
            pobj.msg(f'&<245>{line}&n')
        else:
            pobj.msg(line)
    return

if 'rem' in switches:
    if not dobj or prep != '=' or not iobj:
        pobj.msg('Usage: @wearpos/rem <item> = <pos1>, <pos2>, ...')
        return
    candidates = list(pobj.contents) + list(pobj.location.contents)
    target = bmatch(dobj, pobj, candidates, db)
    if not target:
        pobj.msg("I don't see '%s' here." % dobj)
        return
    wear_pos = target.wear_pos or []
    if not wear_pos:
        pobj.msg("%s has no wear positions." % target.name)
        return
    try:
        to_remove = [int(x.strip()) for x in iobj.split(',')]
    except ValueError:
        pobj.msg("Positions must be integers: @wearpos/rem <item> = 1, 7, 16")
        return
    removed = []
    kept = []
    for entry in wear_pos:
        if entry[0] in to_remove:
            removed.append(entry)
        else:
            kept.append(entry)
    if not removed:
        pobj.msg("No matching positions found to remove.")
        return
    target.wear_pos = kept
    target._mark_modified()
    pobj.msg(f'Removed from &<245>#{target.objnum}:{target.name}&n:')
    for ps in removed:
        pobj.msg('  %3d  %-20s  layer %d' % (ps[0], pos_label(ps[0]), ps[1]))
    if kept:
        pobj.msg('Remaining:')
        for ps in kept:
            pobj.msg('  %3d  %-20s  layer %d' % (ps[0], pos_label(ps[0]), ps[1]))
    else:
        pobj.msg('No wear positions remain.')
    return

if not args:
    items = sorted(positions.items())
    half = (len(items) + 1) // 2
    pobj.msg('Wear positions (%d total):' % len(positions))
    for i in range(half):
        left = items[i]
        line = '  %3d  %-15s' % (left[0], left[1])
        if i + half < len(items):
            right = items[i + half]
            line += '  %3d  %s' % (right[0], right[1])
        pobj.msg(line)
elif prep == '=':
    candidates = list(pobj.contents) + list(pobj.location.contents)
    target = bmatch(dobj, pobj, candidates, db)
    if not target:
        pobj.msg("I don't see '%s' here." % dobj)
        return
    val_str = iobj.strip() if iobj else ''
    if not val_str:
        pobj.msg("Value must be a list of [pos, layer] pairs.")
        return
    try:
        value = eval(val_str)
    except Exception as e:
        pobj.msg("Bad value: %s" % e)
        return
    if not isinstance(value, list):
        pobj.msg("Value must be a list of [pos, layer] pairs.")
        return
    # Allow single [pos, layer] pair without double brackets
    if len(value) == 2 and all(isinstance(x, int) for x in value):
        value = [value]
    for entry in value:
        if not isinstance(entry, list) or len(entry) != 2:
            pobj.msg("Each entry must be [pos, layer]. Bad entry: %s" % repr(entry).replace('&', '&&'))
            return
        if not valid_pos(entry[0]):
            pobj.msg("Unknown position: %d" % entry[0])
            return
    target.wear_pos = value
    pobj.msg(f'Set wear_pos on &<245>#{target.objnum}:{target.name}&n:')
    for ps in value:
        pos, layer = ps[0], ps[1]
        pobj.msg('  %3d  %-20s  layer %d' % (pos, pos_label(pos), layer))
else:
    spec = args.strip() if args else ''
    candidates = list(pobj.contents) + list(pobj.location.contents)
    target = bmatch(spec, pobj, candidates, db)
    if not target:
        pobj.msg("I don't see '%s' here." % dobj)
        return
    wear_pos = target.wear_pos or []
    if not wear_pos:
        pobj.msg("%s has no wear positions." % target.name)
        return
    layer_flex = target.layer_flex or {}
    if isinstance(layer_flex, dict):
        layer_flex = {int(k): v for k, v in layer_flex.items()}
    pobj.msg(f'Wear positions on &<245>#{target.objnum}:{target.name}&n:')
    for ps in wear_pos:
        pos, layer = ps[0], ps[1]
        if pos >= 100:
            r = pos % 100
            l = r - 1
            for rp in [l, r]:
                flex = layer_flex.get(rp, False)
                flex_str = ' [flex]' if flex else ''
                name = positions.get(rp, '???')
                pobj.msg('  %3d  %-20s  layer %d%s' % (rp, name, layer, flex_str))
        else:
            flex = layer_flex.get(pos, False)
            flex_str = ' [flex]' if flex else ''
            pobj.msg('  %3d  %-20s  layer %d%s' % (pos, pos_label(pos), layer, flex_str))
