"""
Lists the tasks the server is currently running.

Usage: @ps
       @ps <player>

Arguments:
    player - Optional: show only tasks belonging to this character.

Switches:
    /all   - Include recently finished tasks as well.
    /me    - Only your own tasks.

Auth: gm3+ (auth_level 3)

fork() and the ticker system both create tasks, and until now there was
no way to see one. A forked task that loops has no other remedy: it does
not appear in any listing, and nothing short of a restart stops it.

Columns:
    ID       task id, which is what @kill takes
    STATE    running, suspended, or done
    PLAYER   the character the task belongs to
    VERB     what it is executing
    AGE      seconds since the task was created
    WAKES    seconds until a suspended task resumes
    TICKS    instruction ticks consumed

A task suspended for a long time is normal -- that is what delay() and
the tickers do. One that is running with a large tick count and does not
finish is the one worth looking at.
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

include_done = 'all' in switches

try:
    tasks = task_list(include_done=include_done)
except RuntimeError as exc:
    pobj.msg(f"Cannot read the task queue: {exc}")
    return

# Narrow to one player, either named or 'me'.
who = None
if 'me' in switches:
    who = pobj
elif args and args.strip():
    candidates = list(pobj.location.contents) + list(pobj.contents)
    who = bmatch(args.strip(), pobj, candidates, db)
    if not who:
        pobj.msg(f"'{args.strip()}' not found.")
        return

if who is not None:
    tasks = [t for t in tasks if t['player'] == who.objnum]

pobj.msg("")
if not tasks:
    whose = f" for {who.name}" if who is not None else ""
    pobj.msg(f"No tasks{whose}." + ("" if include_done else "  (/all includes finished ones.)"))
    return

# Sort so the interesting ones are at the top: running first, then the
# longest-lived, since a task that has been around a while is the one you
# are usually hunting.
_order = {'running': 0, 'suspended': 1, 'pending': 2, 'done': 3}
tasks.sort(key=lambda t: (_order.get(t['state'], 9), -t['age']))

pobj.msg("&<245>   ID  STATE      PLAYER  VERB                 AGE    WAKES   TICKS&n")
for t in tasks:
    player = f"#{t['player']}" if t['player'] else '-'
    verb = (t['verb'] or '-')[:20]
    wakes = f"{t['resumes_in']:.1f}" if t['resumes_in'] else '-'
    forked = f" (forked by {t['parent']})" if t['parent'] else ''
    pobj.msg(f"  {t['id']:>4}  {t['state']:<9}  {player:<6}  {verb:<20} "
             f"{t['age']:>5.1f}  {wakes:>6}  {t['ticks']:>6}{forked}")

pobj.msg("")
running = sum(1 for t in tasks if t['state'] == 'running')
susp = sum(1 for t in tasks if t['state'] == 'suspended')
pobj.msg(f"&<245>-- {len(tasks)} task{'' if len(tasks) == 1 else 's'}: "
         f"{running} running, {susp} suspended.  @kill <id> to stop one.&n")
