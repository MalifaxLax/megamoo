"""
_tick verb on #53 (effects_utils).

Periodic ticker callback that drives the effects system. Called by the
ticker system at regular intervals. Iterates through all registered
effects in fx_registry, fires any that are due (next_fire <= now),
and calls the corresponding do_{name} verb on each effect's target.

Each effect entry in fx_registry tracks:
    objnum    - Target character's object number.
    name      - Effect name (used to call do_{name} verb).
    tick      - Current tick count (incremented each fire).
    remaining - Ticks remaining before expiration.
    interval  - Seconds between fires.
    next_fire - Timestamp of next scheduled fire.
    args/kwargs - Additional arguments passed to the do_ verb.

Expired effects are removed from the registry. If the registry becomes
empty, the ticker is removed entirely.

Hidden:  yes
"""

import time
now = time.time()
registry = this.fx_registry or {}
if not registry:
    ticker_remove(this, 'effect_dispatcher')
    return

expired = []
for key in list(registry):
    e = registry[key]
    if now < e['next_fire']:
        continue

    # Resolve target
    try:
        target = db.get_object(e['objnum'])
    except (KeyError, Exception):
        expired.append(key)
        continue

    e['tick'] += 1
    e['remaining'] -= 1

    # Call do_{name} with target as pobj
    target_cv = make_call_verb(target, db)
    try:
        target_cv(this, f"do_{e['name']}",
                  tick=e['tick'], remaining=e['remaining'],
                  effect_args=e.get('args', []),
                  effect_kwargs=e.get('kwargs', {}))
    except KeyError:
        expired.append(key)  # do_ verb doesn't exist
        continue
    except Exception as err:
        # The comment said "log but don't cancel" and then did not log, so
        # a failing effect handler ticked silently for as long as the
        # effect lasted.  Not cancelling is still right -- one bad tick
        # should not end an effect -- but it has to be visible.
        server_log(f"effect {key} tick failed: {err}", is_error=True)

    if e['remaining'] <= 0:
        expired.append(key)
    else:
        e['next_fire'] = now + e['interval']

for key in expired:
    del registry[key]

this.fx_registry = registry if registry else {}
if not registry:
    ticker_remove(this, 'effect_dispatcher')
