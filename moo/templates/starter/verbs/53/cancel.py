"""
cancel verb on #53 (effects_utils).

Cancels one or all active effects on a target character. Delegates to
the Python EffectsManager.

Method-call interface: $eu.cancel(target, 'effect_name')
                       $eu.cancel(target)  -- cancels all effects

Arguments (via _pyargs):
    target      - The character object to cancel effects on.
    effect_name - Optional specific effect to cancel. If omitted,
                  cancels all active effects on the target.

Hidden:  yes
"""

result = _effects.cancel(*_pyargs)
