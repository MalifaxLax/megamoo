# 05 — Engine Systems

Three runtime systems sit between "a verb runs once when typed" and "the world
has ongoing, reactive behavior": **hooks** (verbs that fire on engine lifecycle
events), the **ticker** (verbs that fire on a schedule), and **effects** (a
higher-level timed buff/debuff layer built on the ticker). All three are
available to any verb author; none require engine changes.

- [Hooks](#hooks)
- [The ticker system](#the-ticker-system)
- [The effects system](#the-effects-system)

---

## Hooks

A **hook** is a named lifecycle event the engine fires while performing an action
— moving an object, recycling it, a player connecting. Verb code can intercept
the event by defining a verb with the right name on the affected object (or any
ancestor). For *cancellable* hooks, the verb can return `False` to veto the
action. The system lives in `moo/hooks.py`.

### How resolution works

Each hook point maps a logical name to a list of **verb-name aliases**. When the
engine calls `fire_hook("before_move", obj, args)`, it searches `obj` and its
inheritance chain for a verb matching any of that hook's aliases; the first match
runs. If none exists, nothing happens (hooks are opt-in). So to react to an
event, you just add a verb with one of the alias names to the object that should
react.

```python
fire_hook(hook_point, obj, args_str="")   # returns the verb's result (or None)
```

For a cancellable hook, `fire_hook` returns `False` when the hook verb returned
`False`, and the engine aborts the pending action.

### The hook registry

These hook points are registered at startup. The **alias** column lists the verb
names you can define to handle the event; the first is canonical.

| Hook | Fired on | Cancellable | Aliases (verb names you define) |
|---|---|---|---|
| `before_move` | the mover | ✅ | `at_before_move`, `at_pre_move` |
| `before_leave` | old location | ✅ | `at_before_leave` |
| `before_enter` | destination | ✅ | `at_before_enter` |
| `after_move` | the mover | — | `at_after_move`, `at_post_move` |
| `after_leave` | old location | — | `at_after_leave`, `exit_func` |
| `after_enter` | destination | — | `at_after_enter`, `enter_func` |
| `object_creation` | the new object | — | `at_object_creation` |
| `before_recycle` | object being deleted | ✅ | `at_before_recycle` |
| `object_delete` | location of the deleted object | — | `at_object_delete` |
| `before_reparent` | object being reparented | ✅ | `at_before_reparent`, `at_pre_reparent` |
| `after_reparent` | object after reparenting | — | `at_after_reparent`, `at_post_reparent` (args = old parent #) |
| `on_disconnect` | player object | — | `at_disconnect`, `on_disconnect` |
| `on_puppet` | character | — | `at_puppet`, `on_puppet` (fires after move to `last_location`) |
| `on_unpuppet` | character | — | `at_unpuppet`, `on_unpuppet` (fires before storage in #2) |

Note the `enter_func` / `exit_func` aliases on `after_enter` / `after_leave` —
that's how containers and rooms run arrival/departure logic. The `at_post_move`
alias on `after_move` is the standard "auto-look on arrival" hook (defined on #3
so every character inherits it).

### A movement is a sequence of hooks

`move()` doesn't fire one hook — it fires a sequence, any of whose *before* hooks
can cancel the whole move:

1. `before_move` on the mover (cancellable)
2. `before_leave` on the old location (cancellable)
3. `before_enter` on the destination (cancellable)
4. — the move happens —
5. `after_move` on the mover, `after_leave` on the old location, `after_enter` on
   the destination

### Examples

Block movement while a condition holds (cancellable before-hook):

```python
# verb 'at_before_move' on a character
if getattr(pobj, 'rooted', 0):
    pobj.msg("You can't move — your feet are rooted to the floor!")
    result = False     # cancels the move
```

React after a player arrives (informational after-hook):

```python
# verb 'at_after_enter' (or 'enter_func') on a room
this.msg_room("%S arrives.", exclude=[pobj], sub=pobj)
```

### Registering your own hook

Game code can add hook points at runtime:

```python
register_hook(name, aliases, cancellable=False, description="")
list_hooks()              # all registered hooks + metadata
is_cancellable(name)      # True for before-hooks
```

`register_hook("before_say", ["at_before_say"], cancellable=True, ...)` then lets
any object veto or rewrite speech by defining `at_before_say`.

---

## The ticker system

The ticker is the engine's heartbeat: "call this verb on this object every N
seconds." It is the timing backbone for the effects system, round-time
countdowns, NPC behavior loops, and any recurring behavior. It lives in
`moo/ticker.py`.

### API

```python
ticker_add(interval, verb_name, obj, idstring='')   # subscribe
ticker_remove(obj, idstring='')                      # remove one subscription
ticker_remove_all(obj)                               # remove all for an object
ticker_list(obj=None)                                # list subscriptions
```

| Parameter | Meaning |
|---|---|
| `interval` | Seconds between fires (float). |
| `verb_name` | The verb to call on `obj` each tick. |
| `obj` | Target object (a `MOOObject` or an objnum). |
| `idstring` | Unique label for this subscription on that object. |

The `idstring` must be unique per object; re-adding with the same object +
idstring **replaces** the existing subscription. Conventionally it embeds the
objnum, e.g.:

```python
ticker_add(1, '_td_rt', pobj, f'_td_rt_{pobj.objnum}')   # tick down round-time every second
```

### Resolution and threading

The ticker has **1-second resolution**: the event loop checks once per second for
due subscriptions. Tick callbacks run on the **same single verb-execution worker**
as player commands (see [Architecture](01-architecture.md#concurrency-model)), so
they never run concurrently with a command or with each other — no locking
required inside tick verbs.

### Persistence

Subscriptions are stored in the **`tickers` table of the SQLite database**, so
they survive restarts. On startup every subscription is reloaded and its
`next_fire` is recalculated from the current time. (The older one-file-per-object
builds wrote a `tickers.json`; the current SQLite engine uses the table.)

### Self-cancelling tickers

A common pattern: a tick verb that counts a property down and removes its own
subscription when it reaches zero. The round-time / status countdown machinery on
`#1` drives many timers (`rt`, and status/condition counters) through a single
configurable tick-down verb, each removing itself when it expires — so idle
characters carry no live tickers.

---

## The effects system

Effects are timed, repeating, optionally-stacking modifiers — poison ticking
damage, regeneration restoring it, intoxication wearing off — built on top of the
ticker. The whole system is one utility object: **#53**, reached as **`$eu`**.
Source: `moo/effects.py`, with the callable verbs in `moo verbs/53/`.

> **Write `$eu`, not `eu`.** There is no bare `eu` name in the verb namespace.
> `$eu` is a [named object constant](02-writing-verbs.md#named-object-constants):
> the preprocessor rewrites it to `db.get_object(0).eu`, which resolves to #53.
> The namespace does also carry the manager module as `_effects`, but `$eu` is
> the form to use.

### API

```python
$eu.trigger(pobj, name, ticks, interval, *args, **kwargs)
$eu.trigger_all(pobj, effects_list)
$eu.cancel(pobj, name=None)
$eu.list_active(pobj)
```

| Method | Purpose |
|---|---|
| `trigger(pobj, name, ticks, interval, *args, **kwargs)` | Apply an effect that fires `ticks` times, `interval` seconds apart. Extra args are forwarded to the callback. |
| `trigger_all(pobj, effects_list)` | Apply several at once; each item is `(name, ticks, interval, *extra)`. |
| `cancel(pobj, name=None)` | Cancel one named effect, or all effects on `pobj` if `name` is omitted. |
| `list_active(pobj)` | Return the active effects on `pobj` (name, remaining, tick, interval). |

```python
$eu.trigger(pobj, "poison", 5, 3, damage=10)       # 5 ticks, every 3s, 10 dmg each
$eu.trigger_all(pobj, [("poison", 5, 3, 10), ("regen", 10, 6)])
```

### Effect callbacks

Each effect named `X` is implemented by a verb `do_X` on #53. When the effect
fires, the engine calls `do_X` with:

| Variable | Meaning |
|---|---|
| `pobj` | The target the effect is on. |
| `tick` | Current fire count (1-based). |
| `remaining` | Ticks left after this fire. |

```python
# do_intoxicate on #53
if tick == 1:
    pobj.msg("Your vision begins to blur...")
pobj.msg("The world sways around you." if remaining else "Your head begins to clear.")
```

Adding a new effect type is therefore just: write a `do_<name>` verb on #53, then
`$eu.trigger(pobj, "<name>", ...)` from anywhere.

### Stacking and persistence

Calling `trigger` again with the same target, name, interval, and args **stacks**
— it adds to the remaining ticks rather than creating a duplicate. Active effects
live in the `fx_registry` property on #53, so (being a property on a database
object) they persist across restarts.

### The dispatcher

A hidden `_tick` verb on #53 is registered as a 1-second ticker. Each second it
scans `fx_registry`, fires every effect whose `next_fire` is due, and — when the
registry empties — removes its own ticker so an idle world spends no cycles on
effects. This is the effects system eating its own dog food: it's just a ticker
plus a dict.

---

Next: [The Prototype Library](06-object-prototypes.md) — the shippable base
objects (rooms, exits, containers, furniture, wearables, consumables) and their
properties.
