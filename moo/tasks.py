"""
MegaMOO Task Management System

This module implements the MOO task system for verb execution, including
task queuing, scheduling, suspension, and resource management.

Overview
--------
Every verb execution in MegaMOO runs inside a **Task**. Tasks are the
fundamental unit of work: when a player types a command, the resulting verb
call is wrapped in a Task that tracks its execution state, resource
consumption, and context (who called it, on what object, with what arguments).

Tasks in MOO:
    - Each verb execution is a task.
    - Tasks have time limits (ticks) and wall-clock limits (seconds) to
      prevent runaway code from hanging the server.
    - Tasks can be **suspended** (``suspend(seconds)``) and will automatically
      resume after the delay expires, e.g. for timed sequences.
    - Tasks can **fork** -- creating a child task that runs independently.
      Fork depth is limited to prevent infinite fork-bombs.
    - Each task carries a **TaskContext** with the standard MOO built-in
      variables (``player``, ``this``, ``caller``, ``verb``, ``args``,
      ``dobj``/``iobj`` strings, etc.).

Architecture
------------
::

    Player command
        |
        v
    MegaMOOServer.execute_command()
        |
        v
    create_task(player, obj, verb, args)  <-- this module
        |
        v
    TaskQueue.queue_task(task, priority)
        |
        v
    TaskQueue.get_next_task()  --> Task.start() --> verb execution
        |                                          |
        v                                          v
    Task completes / errors / suspends       check_limits()

The global singleton ``TaskQueue`` (accessed via ``get_task_queue()``) is
the central scheduler. The server's background loop polls it for the next
ready task, which may be a brand-new pending task or a previously
suspended task whose resume time has arrived.

Threading
---------
Task IDs are allocated under a threading lock (``_task_id_lock``) so they
are safe to generate from any thread. The ``TaskQueue`` itself is also
lock-protected for thread safety, since verb execution runs in a dedicated
``ThreadPoolExecutor`` worker while the asyncio event loop manages I/O
concurrently (see ``server.py``).

See Also
--------
- ``server.py`` -- orchestrates task creation and execution.
- ``verb_context.py`` -- the ``ContextVar`` that carries (pobj, db, depth)
  into verb code running on the thread-pool worker.
- ``builtins.py`` -- provides ``fork()``, ``suspend()``, ``kill_task()``
  wrappers that delegate to this module.

Copyright (c) 2026
License: MIT
"""

# =============================================================================
# IMPORTS
# =============================================================================

from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from collections import deque
from enum import Enum
import time
import threading
import logging
from queue import PriorityQueue

logger = logging.getLogger('megamoo.tasks')


# =============================================================================
# TASK STATE ENUMERATION
# =============================================================================


class TaskState(Enum):
    """
    Possible execution states of a Task.

    Tasks progress through these states during their lifecycle::

        PENDING ──> RUNNING ──> COMPLETED
                       |    \\──> ERROR
                       |    \\──> ABORTED
                       v
                    SUSPENDED ──> RUNNING (resumed)

    Attributes:
        PENDING:    Task is in the queue, waiting to be dispatched.
        RUNNING:    Task is actively executing verb code.
        SUSPENDED:  Task has called ``suspend(seconds)`` and is waiting
                    for its timer to expire before resuming.
        COMPLETED:  Task finished successfully; ``result`` contains the
                    return value.
        ABORTED:    Task was killed externally (e.g. ``kill_task()``) or
                    exceeded resource limits.
        ERROR:      Task terminated due to an unhandled exception; the
                    ``error`` attribute contains the Exception.
    """
    PENDING = 'pending'      # Waiting to run
    RUNNING = 'running'      # Currently executing
    SUSPENDED = 'suspended'  # Suspended, will resume
    COMPLETED = 'completed'  # Finished successfully
    ABORTED = 'aborted'      # Terminated early
    ERROR = 'error'          # Terminated with error


# =============================================================================
# TASK CONTEXT -- built-in variables available during verb execution
# =============================================================================


@dataclass
class TaskContext:
    """
    Context information for a running task.

    This corresponds to the standard built-in variables available in MOO
    verb code. When a player types ``put ball in box``, the parser
    populates these fields so the verb can inspect what was said::

        player  = #42          (the player who typed the command)
        this    = #100         (object the verb is defined on)
        caller  = #42          (object that initiated the call)
        verb    = 'put_in'     (matched verb name)
        args    = ['ball']     (parsed argument tokens)
        argstr  = 'ball in box' (raw argument string)
        dobj    = #55          (direct object -- the ball)
        dobjstr = 'ball'       (direct object as typed)
        prepstr = 'in'         (preposition as typed)
        iobj    = #60          (indirect object -- the box)
        iobjstr = 'box'        (indirect object as typed)
        perms   = #42          (effective permissions obj)

    Attributes:
        player (int): Player who initiated the task (object number).
        this (int): Object the verb is defined on (object number).
        caller (int): Calling object for verb-to-verb calls (0 if none).
        verb (str): Name of the verb being executed.
        args (list): Parsed argument list.
        argstr (str): Full argument string (unparsed).
        dobj (int): Direct object number (0 if none).
        dobjstr (str): Direct object string as typed by the player.
        prepstr (str): Preposition string (e.g. "in", "on", "with").
        iobj (int): Indirect object number (0 if none).
        iobjstr (str): Indirect object string as typed by the player.
        perms (int): Effective permissions object number for this task.
    """
    player: int
    this: int
    caller: int = 0
    verb: str = ''
    args: list = field(default_factory=list)
    argstr: str = ''
    dobj: int = 0
    dobjstr: str = ''
    prepstr: str = ''
    iobj: int = 0
    iobjstr: str = ''
    perms: int = 0


# =============================================================================
# TASK RESOURCE LIMITS
# =============================================================================


@dataclass
class TaskLimits:
    """
    Resource limits for task execution.

    These limits prevent runaway verb code from monopolising server
    resources. When any limit is exceeded, the task is aborted and an
    error is reported to the player.

    Typical defaults match classic LambdaMOO conventions, though the
    exact numbers are tuned for MegaMOO's Python execution model.

    Attributes:
        max_ticks (int): Maximum number of "instruction ticks" a task
            may consume. Each significant operation (property access,
            verb call, loop iteration) increments the tick counter.
            Default: 100,000.
        max_seconds (int): Maximum wall-clock seconds a task may run.
            This is a hard safety net independent of ticks.
            Default: 5.
        max_stack_depth (int): Maximum depth of the verb call stack
            (verb calling verb calling verb...). Prevents infinite
            recursion. Default: 50.
        max_fork_depth (int): Maximum nesting depth of forked tasks.
            Prevents fork-bombs. Default: 10.
    """
    max_ticks: int = 100000      # Instructions
    max_seconds: int = 5          # Wall-clock seconds
    max_stack_depth: int = 50     # Call depth
    max_fork_depth: int = 10      # Fork depth


# =============================================================================
# TASK -- a single unit of verb execution
# =============================================================================


class Task:
    """
    A single MOO task representing one verb execution.

    Tasks are the core scheduling primitive. Each task has its own
    context (who/what/where), resource limits, and lifecycle state.
    Tasks are created by ``create_task()``, queued via ``TaskQueue``,
    and progress through the states defined in ``TaskState``.

    Class-Level State:
        ``_next_task_id`` and ``_task_id_lock`` provide a process-wide
        monotonically increasing task ID counter, protected by a
        threading lock for safe concurrent allocation.

    Attributes:
        task_id (int): Unique task identifier (auto-assigned).
        context (TaskContext): The MOO built-in variables for this task.
        limits (TaskLimits): Resource limits governing execution.
        state (TaskState): Current execution state.
        created_time (float): Unix timestamp when the task was created.
        start_time (float): Unix timestamp when the task began running
            (0.0 if not yet started).
        end_time (float): Unix timestamp when the task completed, was
            aborted, or errored (0.0 if still active).
        ticks_used (int): Number of instruction ticks consumed so far.
        suspended_until (float): Unix timestamp at which a suspended
            task should resume (0.0 if not suspended).
        parent_task_id (int): Task ID of the parent task if this task
            was created by ``fork()``; 0 for top-level tasks.
        result (Any): Return value when the task completes successfully.
        error (Exception): The exception if the task terminated with
            an error.
        call_stack (List[Dict[str, Any]]): Stack frames tracking nested
            verb-to-verb calls within this task.
        fork_depth (int): How many levels of forking deep this task is.
    """

    # --- Class-level task ID allocator (thread-safe) ---
    _next_task_id = 1
    _task_id_lock = threading.Lock()

    @classmethod
    def _get_next_task_id(cls) -> int:
        """
        Allocate the next unique task ID.

        Thread-safe: uses ``_task_id_lock`` so multiple threads (e.g.
        the asyncio loop and the verb-execution thread) can safely
        allocate IDs concurrently.

        Returns:
            int: A monotonically increasing unique task ID.
        """
        with cls._task_id_lock:
            task_id = cls._next_task_id
            cls._next_task_id += 1
            return task_id

    def __init__(self, context: TaskContext, limits: Optional[TaskLimits] = None,
                 parent_task_id: int = 0):
        """
        Initialize a new task.

        Args:
            context: TaskContext with the MOO built-in variables for
                this execution (player, this, verb, args, etc.).
            limits: Resource limits for this task. If ``None``, default
                ``TaskLimits()`` values are used.
            parent_task_id: If this task was created by ``fork()``,
                the parent task's ID. Defaults to 0 (top-level).
        """
        self.task_id = self._get_next_task_id()
        self.context = context
        self.limits = limits or TaskLimits()
        self.state = TaskState.PENDING
        self.created_time = time.time()
        self.start_time = 0.0
        self.end_time = 0.0
        self.ticks_used = 0
        self.suspended_until = 0.0
        self.parent_task_id = parent_task_id
        self.result = None
        self.error = None

        # Execution state
        self.call_stack: List[Dict[str, Any]] = []
        self.fork_depth = 0
        if parent_task_id > 0:
            # Inherit fork depth from parent (would need to look up parent)
            self.fork_depth = 1

    def __repr__(self) -> str:
        return f"Task({self.task_id}, {self.state.value}, verb={self.context.verb})"

    # -----------------------------------------------------------------
    # State transitions
    # -----------------------------------------------------------------

    def start(self):
        """
        Transition the task from PENDING to RUNNING.

        Records the start timestamp for wall-clock limit enforcement.
        Called by ``TaskQueue.get_next_task()`` when the task is
        dispatched for execution.
        """
        self.state = TaskState.RUNNING
        self.start_time = time.time()

    def complete(self, result: Any = None):
        """
        Mark the task as successfully completed.

        Args:
            result: The return value produced by the verb execution.
                Stored in ``self.result`` for the caller to retrieve.
        """
        self.state = TaskState.COMPLETED
        self.end_time = time.time()
        self.result = result
        logger.debug(f"Task {self.task_id} completed")

    def abort(self):
        """
        Abort task execution.

        Called when the task is killed externally (e.g. via
        ``kill_task()`` or when resource limits are exceeded). The
        task moves to the ABORTED state and is removed from the
        active queues.
        """
        self.state = TaskState.ABORTED
        self.end_time = time.time()
        logger.debug(f"Task {self.task_id} aborted")

    def error_exit(self, error: Exception):
        """
        Mark the task as terminated due to an error.

        Args:
            error: The exception that caused the task to fail.
                Stored in ``self.error`` for debugging.
        """
        self.state = TaskState.ERROR
        self.end_time = time.time()
        self.error = error
        logger.debug(f"Task {self.task_id} error: {error}")

    def suspend(self, seconds: float):
        """
        Suspend the task for a specified duration.

        The task transitions to SUSPENDED and records the wall-clock
        time at which it should resume. The ``TaskQueue`` will
        automatically detect when the suspension expires and re-dispatch
        the task.

        This is used by the ``suspend(seconds)`` builtin available in
        verb code, e.g.::

            notify(player, "You begin meditating...")
            suspend(5)
            notify(player, "You feel refreshed.")

        Args:
            seconds: Number of seconds to suspend. May be fractional
                (e.g. ``0.5`` for half a second).
        """
        self.state = TaskState.SUSPENDED
        self.suspended_until = time.time() + seconds
        logger.debug(f"Task {self.task_id} suspended for {seconds}s")

    # -----------------------------------------------------------------
    # Status checks
    # -----------------------------------------------------------------

    def is_ready(self) -> bool:
        """
        Check if a suspended task is ready to resume execution.

        Returns:
            bool: ``True`` if the task is SUSPENDED and its resume
                time has arrived (or passed). ``False`` otherwise.
        """
        if self.state != TaskState.SUSPENDED:
            return False
        return time.time() >= self.suspended_until

    def check_limits(self) -> bool:
        """
        Check whether the task has exceeded any of its resource limits.

        Examines tick count, wall-clock time, call-stack depth, and
        fork depth against the configured ``TaskLimits``. If any limit
        is exceeded, a warning is logged.

        Returns:
            bool: ``True`` if all limits are within bounds (task may
                continue). ``False`` if any limit has been exceeded
                (task should be aborted).
        """
        # Check ticks (instruction count)
        if self.ticks_used >= self.limits.max_ticks:
            logger.warning(f"Task {self.task_id} exceeded tick limit")
            return False

        # Check wall-clock time
        if self.start_time > 0:
            elapsed = time.time() - self.start_time
            if elapsed >= self.limits.max_seconds:
                logger.warning(f"Task {self.task_id} exceeded time limit")
                return False

        # Check verb call stack depth (prevents infinite recursion)
        if len(self.call_stack) >= self.limits.max_stack_depth:
            logger.warning(f"Task {self.task_id} exceeded stack depth")
            return False

        # Check fork nesting depth (prevents fork-bombs)
        if self.fork_depth >= self.limits.max_fork_depth:
            logger.warning(f"Task {self.task_id} exceeded fork depth")
            return False

        return True

    # -----------------------------------------------------------------
    # Tick accounting
    # -----------------------------------------------------------------

    def tick(self, count: int = 1):
        """
        Increment the instruction tick counter.

        Each significant operation in verb execution should call this
        to track resource consumption. When ``ticks_used`` reaches
        ``limits.max_ticks``, ``check_limits()`` will return ``False``
        and the task will be aborted.

        Args:
            count: Number of ticks to add (default 1).
        """
        self.ticks_used += count

    def ticks_left(self) -> int:
        """
        Get the number of remaining ticks before the limit is hit.

        Returns:
            int: Remaining ticks (never negative).
        """
        return max(0, self.limits.max_ticks - self.ticks_used)

    def seconds_left(self) -> float:
        """
        Get the remaining wall-clock seconds before the time limit.

        If the task has not started yet, returns the full time budget.

        Returns:
            float: Remaining seconds (never negative).
        """
        if self.start_time == 0:
            return self.limits.max_seconds
        elapsed = time.time() - self.start_time
        return max(0, self.limits.max_seconds - elapsed)


# =============================================================================
# TASK QUEUE -- schedules and dispatches tasks
# =============================================================================


class TaskQueue:
    """
    Manages task scheduling, dispatching, and lifecycle tracking.

    The TaskQueue is the central scheduler for all verb execution. It
    maintains three pools of tasks:

    1. **Pending tasks** -- in a priority queue, waiting to be dispatched.
       Lower priority numbers run first. Ties are broken by creation time
       (FIFO within the same priority level).
    2. **Running tasks** -- currently being executed by the verb engine.
    3. **Suspended tasks** -- paused via ``suspend(seconds)``, waiting for
       their timer to expire.

    A bounded history of recently completed/aborted/errored tasks is kept
    for diagnostic introspection (e.g. the ``@tasks`` wizard command).

    Thread Safety:
        All public methods acquire ``self.lock`` before modifying internal
        state. This is necessary because the asyncio event loop and the
        verb-execution thread pool may interact concurrently.

    Attributes:
        pending_tasks (PriorityQueue): Priority queue of tasks waiting
            to run. Items are tuples of (priority, created_time,
            task_id, task) for correct ordering.
        running_tasks (Dict[int, Task]): Currently executing tasks,
            keyed by task_id.
        suspended_tasks (Dict[int, Task]): Suspended tasks waiting to
            resume, keyed by task_id.
        completed_tasks (deque): Bounded deque of recently finished
            tasks (for history/debugging).
        max_history (int): Maximum number of completed tasks to retain.
    """

    def __init__(self, max_history: int = 100):
        """
        Initialize the task queue.

        Args:
            max_history: Maximum number of completed/aborted/errored
                tasks to keep in the history deque. Older entries are
                automatically discarded. Default: 100.
        """
        self.pending_tasks = PriorityQueue()
        self.running_tasks: Dict[int, Task] = {}
        self.suspended_tasks: Dict[int, Task] = {}
        self.completed_tasks: deque = deque(maxlen=max_history)
        self.max_history = max_history
        self.lock = threading.Lock()

    # -----------------------------------------------------------------
    # Task submission
    # -----------------------------------------------------------------

    def queue_task(self, task: Task, priority: int = 0):
        """
        Add a task to the pending queue.

        The task is enqueued with the given priority. Lower priority
        values are dispatched first. Within the same priority level,
        tasks are dispatched in FIFO order (by creation time, then
        by task_id as a final tiebreaker).

        Args:
            task: The Task instance to enqueue.
            priority: Scheduling priority (lower = higher priority).
                Default: 0.
        """
        with self.lock:
            # Tuple ordering: (priority, created_time, task_id, task)
            # PriorityQueue sorts by the tuple elements in order,
            # giving us priority-first, then FIFO within same priority.
            self.pending_tasks.put((priority, task.created_time, task.task_id, task))
            logger.debug(f"Queued task {task.task_id} with priority {priority}")

    # -----------------------------------------------------------------
    # Task dispatching
    # -----------------------------------------------------------------

    def get_next_task(self) -> Optional[Task]:
        """
        Get the next task that is ready to execute.

        Checks suspended tasks first (in case any have reached their
        resume time), then falls back to the pending queue. This
        ensures that suspended tasks resume promptly rather than
        waiting behind newly queued tasks.

        Returns:
            Task: The next ready task, already transitioned to RUNNING
                state. Returns ``None`` if no tasks are ready.
        """
        with self.lock:
            # First priority: check for suspended tasks ready to resume.
            # This ensures suspended tasks aren't starved by new arrivals.
            for task_id, task in list(self.suspended_tasks.items()):
                if task.is_ready():
                    del self.suspended_tasks[task_id]
                    task.state = TaskState.RUNNING
                    self.running_tasks[task_id] = task
                    logger.debug(f"Resuming task {task_id}")
                    return task

            # Second priority: dequeue the next pending task.
            if not self.pending_tasks.empty():
                _, _, _, task = self.pending_tasks.get()
                task.start()
                self.running_tasks[task.task_id] = task
                return task

        return None

    # -----------------------------------------------------------------
    # Task state transitions (called by the verb engine)
    # -----------------------------------------------------------------

    def suspend_task(self, task: Task, seconds: float):
        """
        Suspend a running task for a specified duration.

        Moves the task from ``running_tasks`` to ``suspended_tasks``.
        The task will be automatically resumed by ``get_next_task()``
        once its suspension timer expires.

        Args:
            task: The currently running task to suspend.
            seconds: Duration of the suspension in seconds.
        """
        with self.lock:
            if task.task_id in self.running_tasks:
                del self.running_tasks[task.task_id]
            task.suspend(seconds)
            self.suspended_tasks[task.task_id] = task

    def complete_task(self, task: Task, result: Any = None):
        """
        Mark a task as successfully completed and archive it.

        Removes the task from ``running_tasks`` and adds it to the
        completed-task history for debugging/introspection.

        Args:
            task: The task that finished execution.
            result: The return value from the verb execution.
        """
        with self.lock:
            if task.task_id in self.running_tasks:
                del self.running_tasks[task.task_id]
            task.complete(result)
            self._add_to_history(task)

    def abort_task(self, task: Task):
        """
        Abort a task, removing it from all active pools.

        Can be called on both running and suspended tasks. The task
        is moved to the ABORTED state and archived in history.

        Args:
            task: The task to abort.
        """
        with self.lock:
            if task.task_id in self.running_tasks:
                del self.running_tasks[task.task_id]
            if task.task_id in self.suspended_tasks:
                del self.suspended_tasks[task.task_id]
            task.abort()
            self._add_to_history(task)

    def error_task(self, task: Task, error: Exception):
        """
        Mark a task as failed due to an error and archive it.

        Args:
            task: The task that encountered an error.
            error: The exception that caused the failure.
        """
        with self.lock:
            if task.task_id in self.running_tasks:
                del self.running_tasks[task.task_id]
            task.error_exit(error)
            self._add_to_history(task)

    # -----------------------------------------------------------------
    # Task lookup
    # -----------------------------------------------------------------

    def get_task(self, task_id: int) -> Optional[Task]:
        """
        Look up a task by its ID across all pools.

        Searches running tasks, suspended tasks, and the completion
        history (in that order).

        Args:
            task_id: The unique task ID to find.

        Returns:
            Task: The matching Task instance, or ``None`` if not found
                in any pool.
        """
        with self.lock:
            # Check running tasks
            if task_id in self.running_tasks:
                return self.running_tasks[task_id]

            # Check suspended tasks
            if task_id in self.suspended_tasks:
                return self.suspended_tasks[task_id]

            # Check completion history (linear scan -- history is bounded)
            for task in self.completed_tasks:
                if task.task_id == task_id:
                    return task

        return None

    def kill_task(self, task_id: int) -> bool:
        """
        Kill a task by its ID.

        Only running and suspended tasks can be killed. Completed,
        aborted, and errored tasks are already finished and cannot
        be killed.

        This is exposed to verb code as the ``kill_task(task_id)``
        builtin, and to wizards via the ``@kill`` command.

        Args:
            task_id: The ID of the task to kill.

        Returns:
            bool: ``True`` if the task was found and killed.
                ``False`` if the task was not found or was already
                in a terminal state.
        """
        task = self.get_task(task_id)
        if task and task.state in (TaskState.RUNNING, TaskState.SUSPENDED):
            self.abort_task(task)
            return True
        return False

    # -----------------------------------------------------------------
    # Introspection (for @tasks, diagnostics)
    # -----------------------------------------------------------------

    def get_queue_info(self) -> Dict[str, Any]:
        """
        Get aggregate statistics about the task queue.

        Useful for monitoring server load and debugging task backlogs.

        Returns:
            dict: A dictionary with the following keys:
                - ``'pending'`` (int): Number of tasks waiting to run.
                - ``'running'`` (int): Number of tasks currently executing.
                - ``'suspended'`` (int): Number of suspended tasks.
                - ``'history_size'`` (int): Number of tasks in the
                  completion history.
        """
        with self.lock:
            return {
                'pending': self.pending_tasks.qsize(),
                'running': len(self.running_tasks),
                'suspended': len(self.suspended_tasks),
                'history_size': len(self.completed_tasks),
            }

    def get_queued_tasks(self) -> List[Dict[str, Any]]:
        """
        Get a list of all active (running + suspended) tasks as dicts.

        This powers the ``@tasks`` wizard command and the API's task
        list endpoint. Each dictionary includes the task's ID, state,
        owning player, verb name, and target object.

        Returns:
            List[Dict[str, Any]]: A list of dictionaries, each
                containing:
                - ``'id'`` (int): Task ID.
                - ``'state'`` (str): Current state string.
                - ``'player'`` (int): Player object number.
                - ``'verb'`` (str): Verb name.
                - ``'this'`` (int): Target object number.
                - ``'resume_at'`` (float): Unix timestamp when a
                  suspended task will resume (suspended tasks only).
        """
        tasks = []

        with self.lock:
            # Running tasks
            for task in self.running_tasks.values():
                tasks.append({
                    'id': task.task_id,
                    'state': task.state.value,
                    'player': task.context.player,
                    'verb': task.context.verb,
                    'this': task.context.this,
                })

            # Suspended tasks
            for task in self.suspended_tasks.values():
                tasks.append({
                    'id': task.task_id,
                    'state': task.state.value,
                    'player': task.context.player,
                    'verb': task.context.verb,
                    'this': task.context.this,
                    'resume_at': task.suspended_until,
                })

        return tasks

    # -----------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------

    def _add_to_history(self, task: Task):
        """
        Add a finished task to the completion history.

        The history is a bounded deque (``maxlen=max_history``), so
        the oldest entries are automatically evicted when the limit
        is reached. No lock is acquired here because all callers
        already hold ``self.lock``.
        """
        self.completed_tasks.append(task)


# =============================================================================
# GLOBAL TASK QUEUE SINGLETON
# =============================================================================

# Module-level singleton, lazily initialised by get_task_queue().
_global_task_queue: Optional[TaskQueue] = None


def get_task_queue() -> TaskQueue:
    """
    Get (or create) the global task queue singleton.

    The task queue is lazily created on first access and then reused
    for the lifetime of the process. All parts of the system that
    need to enqueue or inspect tasks should go through this function.

    Returns:
        TaskQueue: The global task queue instance.
    """
    global _global_task_queue
    if _global_task_queue is None:
        _global_task_queue = TaskQueue()
    return _global_task_queue


# =============================================================================
# CONVENIENCE FUNCTIONS -- used by server.py and builtins.py
# =============================================================================


def create_task(player_objnum: int, this_objnum: int, verb: str,
                args: List[Any], **kwargs) -> Task:
    """
    Create a new Task with a fully populated TaskContext.

    This is the primary entry point for task creation. The server
    calls this when a player command has been parsed and is ready
    for execution.

    Args:
        player_objnum: Object number of the player who initiated
            the command (becomes ``context.player``).
        this_objnum: Object number of the object the verb is
            defined on (becomes ``context.this``).
        verb: Name of the verb to execute (becomes ``context.verb``).
        args: Parsed argument list (becomes ``context.args``).
        **kwargs: Additional TaskContext fields to set (e.g.
            ``argstr``, ``dobj``, ``dobjstr``, ``prepstr``,
            ``iobj``, ``iobjstr``, ``caller``, ``perms``).

    Returns:
        Task: A new Task instance in PENDING state, ready to be
            queued via ``queue_task()``.
    """
    context = TaskContext(
        player=player_objnum,
        this=this_objnum,
        verb=verb,
        args=args,
        **kwargs
    )

    return Task(context)


def queue_task(task: Task, priority: int = 0):
    """
    Queue a task for execution on the global task queue.

    Convenience wrapper around ``get_task_queue().queue_task()``.

    Args:
        task: The Task to enqueue.
        priority: Scheduling priority (lower = higher priority).
            Default: 0.
    """
    queue = get_task_queue()
    queue.queue_task(task, priority)
