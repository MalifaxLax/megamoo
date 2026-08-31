"""
Aborts a running or suspended task.

Usage: @kill <task id>
       @kill all

Arguments:
    task id - The id shown by @ps.
    all     - Abort every task except the one running this command.

Auth: gm3+ (auth_level 3)

A running task stops at its next tick; a suspended one is discarded
without resuming. Either way the task's verb does not finish, so whatever
it was part-way through doing stays part-way done -- this is a way out of
a runaway loop, not a way to undo work.

`@kill all` deliberately spares the task executing this command, which
would otherwise abort itself before reporting anything.
"""
if auth_level(pobj) < 3:
    pobj.msg("Do what?")
    return

target = (args or '').strip()
if not target:
    pobj.msg('Usage: @kill <task id>   (see @ps)')
    pobj.msg('       @kill all')
    return

try:
    tasks = task_list()
except RuntimeError as exc:
    pobj.msg(f"Cannot read the task queue: {exc}")
    return

if target.lower() == 'all':
    if not tasks:
        pobj.msg("No tasks to stop.")
        return
    killed = []
    failed = []
    for t in tasks:
        if t['state'] == 'running' and t['player'] == pobj.objnum:
            continue
        if kill_task(t['id']):
            killed.append(t['id'])
        else:
            failed.append(t['id'])
    if killed:
        pobj.msg(f"Stopped {len(killed)} task{'' if len(killed) == 1 else 's'}: "
                 + ', '.join(str(i) for i in killed))
    else:
        pobj.msg("Nothing to stop.")
    if failed:
        pobj.msg(f"&<245>{len(failed)} had already finished.&n")
    return

if not target.isdigit():
    pobj.msg("Task id must be a number, or 'all'.  See @ps.")
    return

task_id = int(target)
match = next((t for t in tasks if t['id'] == task_id), None)

if kill_task(task_id):
    if match:
        verb = match['verb'] or 'a task'
        pobj.msg(f"Stopped task {task_id} ({match['state']}, {verb}).")
    else:
        pobj.msg(f"Stopped task {task_id}.")
else:
    pobj.msg(f"No task {task_id}.  It may have finished already -- @ps to look.")
