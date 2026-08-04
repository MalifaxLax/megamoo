"""
Remove a mark by its number.

Usage: unmark <number>

Arguments:
    number - The mark number from mark/list to remove.

Auth: none
"""

marks = pobj.marks or []
if not marks:
    pobj.msg("You have no marks.")
    return

if not args:
    pobj.msg("Usage: unmark <number>")
    return

try:
    num = int(args.strip())
except ValueError:
    pobj.msg("Usage: unmark <number>")
    return

if num < 1 or num > len(marks):
    pobj.msg(f"Mark number must be between 1 and {len(marks)}.")
    return

removed = marks.pop(num - 1)
pobj.marks = marks
pobj._mark_modified()
try:
    room = db.get_object(removed)
    pobj.msg(f"Mark {num} removed. ({room.name})")
except Exception:
    pobj.msg(f"Mark {num} removed.")
