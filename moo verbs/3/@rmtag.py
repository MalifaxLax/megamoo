"""
Removes a tag (or entire category) from an object's tag set. Verifies
the tag/category exists before attempting removal.

Usage: @rmtag <object> = <category>[/<tag>]

Arguments:
    object    - The target object (matched in room and inventory).
    category  - The tag category. If no /tag suffix, removes entire category.
    tag       - The specific tag within the category to remove.

Auth: gm3+ (auth_level 3)

Examples:
    @rmtag #15 = zone/haven       Remove a specific tag from a category.
    @rmtag #15 = zone             Remove an entire category.
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

if not dobj or prep != '=':
    pobj.msg("Usage: @rmtag <object> = <category>[/<tag>]")
    pobj.msg("Example: @rmtag #15 = zone/haven")
    pobj.msg("Example: @rmtag #15 = zone  (removes entire category)")
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
    category = category.strip()
    tag = tag.strip() or None
else:
    category = None
    tag = tag_part.strip()

if not tag and not category:
    pobj.msg("No tag specified.")
    return

# Check if it exists before removing
all_tags = target.tags.all()
cat = category or 'general'
if cat not in all_tags:
    if category:
        pobj.msg(f"Category '{category}' not found on %<245>#{target.objnum}:{target.name}%n.")
    else:
        pobj.msg(f"Tag '{tag}' not found on %<245>#{target.objnum}:{target.name}%n.")
    return

if tag and tag not in all_tags.get(cat, []):
    if category:
        pobj.msg(f"Tag '{tag}' not found in category '{category}' on %<245>#{target.objnum}:{target.name}%n.")
    else:
        pobj.msg(f"Tag '{tag}' not found on %<245>#{target.objnum}:{target.name}%n.")
    return

target.tags.remove(tag, category)
if category:
    if tag:
        pobj.msg(f"Removed tag '{tag}' from category '{category}' on %<245>#{target.objnum}:{target.name}%n.")
    else:
        pobj.msg(f"Removed category '{category}' from %<245>#{target.objnum}:{target.name}%n.")
else:
    pobj.msg(f"Removed tag '{tag}' from %<245>#{target.objnum}:{target.name}%n.")
