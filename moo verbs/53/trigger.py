"""
trigger verb on #53 (effects_utils).

Triggers a single named effect on a target character. Registers the
effect in fx_registry with the specified number of ticks and interval
between ticks. Delegates to the Python EffectsManager.

Method-call interface: $eu.trigger(target, 'effect_name', ticks, interval)

Arguments (via _pyargs):
    target      - The character object to apply the effect to.
    effect_name - Name of the effect (matches a do_{name} verb).
    ticks       - Number of times the effect should fire.
    interval    - Seconds between each fire.
"""

result = _effects.trigger(*_pyargs)
