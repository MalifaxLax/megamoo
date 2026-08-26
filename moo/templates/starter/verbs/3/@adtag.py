"""
Adds a tag (with optional category) to an object's tag set. Tags are
used for classification, zone marking, and game-system flags.

Usage: @adtag <object> = <category>[/<tag>]

Arguments:
    object    - The target object (matched in room and inventory).
    category  - Tag category (e.g. 'zone', 'weapon'). Optional if just a tag.
    tag       - The tag value within the category.

Auth: gm3+ (auth_level 3)

Examples:
    @adtag #11 = zone/haven
    @adtag sword = weapon/blade
    @adtag me = staff
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

if not dobj or prep != '=':
    pobj.msg("Usage: @adtag <object> = <category>[/<tag>]")
    pobj.msg("Example: @adtag #11 = zone/haven")
    pobj.msg("Example: @adtag sword = weapon/blade")
    pobj.msg("Example: @adtag me = staff")
    return

tag_part = iobj.strip() if iobj else ''
if not tag_part:
    pobj.msg("No tag specified.")
    return

candidates = list(pobj.contents)
if pobj.location:
    candidates += list(pobj.location.contents)
target = bmatch(dobj, pobj, candidates, db)
if not target:
    pobj.msg(f"Object '{dobj}' not found.")
    return

if '/' in tag_part:
    category, tag = tag_part.split('/', 1)
    category = category.strip() or None
    tag = tag.strip() or None
else:
    category = None
    tag = tag_part.strip()

if not tag and not category:
    pobj.msg("No tag specified.")
    return

target.tags.add(tag, category)
if category and tag:
    pobj.msg(f"Added tag '{tag}' in category '{category}' to &<245>#{target.objnum}:{target.name}&n.")
elif category:
    pobj.msg(f"Added category '{category}' to &<245>#{target.objnum}:{target.name}&n.")
else:
    pobj.msg(f"Added tag '{tag}' to &<245>#{target.objnum}:{target.name}&n.")
