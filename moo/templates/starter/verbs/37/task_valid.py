"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

def task_valid(task_id) -> bool:
        """Whether a task is still queued or running."""
        try:
            from moo.tasks import get_task_queue
            q = get_task_queue()
        except Exception:
            return False
        return bool(q and (task_id in q.running_tasks
                           or task_id in q.suspended_tasks))


_a = kwargs.pop('_pyargs', None)

return task_valid(*(_a if _a is not None else argv), **kwargs)
