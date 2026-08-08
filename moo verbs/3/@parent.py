"""
Usage: @parent <object> = <new_parent>
       @parent #<start> to #<end> = <new_parent>

Changes the parent of an object or range of objects.

Examples:
    @parent #100 = #4
    @parent sword = #30
    @parent #500 to #520 = #1
"""

if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

if not dobj or prep != '=' or not iobj:
    pobj.msg("Usage: @parent <object> = <new_parent>")
    pobj.msg("       @parent #<start> to #<end> = <new_parent>")
    return

# Resolve new parent
candidates = list(pobj.contents) + list(pobj.location.contents)
new_parent = bmatch(iobj.strip(), pobj, candidates, db)
if not new_parent:
    pobj.msg(f"Parent '{iobj}' not found.")
    return

# Check for range: #N to #N
import re
range_match = re.match(r'#(\d+)\s+to\s+#(\d+)', dobj.strip())

if range_match:
    start = int(range_match.group(1))
    end = int(range_match.group(2))
    if start > end:
        start, end = end, start
    count = 0
    errors = 0
    for num in range(start, end + 1):
        try:
            obj = db.get_object(num)
            old_parent = obj.parent
            chparent(obj, new_parent.objnum)
            count += 1
        except Exception as e:
            errors += 1
    pobj.msg(f"Reparented {count} object(s) to &<245>#{new_parent.objnum}:{new_parent.name}&n.")
    if errors:
        pobj.msg(f"  {errors} object(s) skipped (not found or error).")
else:
    # Single object
    target = bmatch(dobj.strip(), pobj, candidates, db)
    if not target:
        pobj.msg(f"Object '{dobj}' not found.")
        return
    old_parent = target.parent
    chparent(target, new_parent.objnum)
    pobj.msg(f"Parent of &<245>#{target.objnum}:{target.name}&n changed from #{old_parent} to &<245>#{new_parent.objnum}:{new_parent.name}&n.")
