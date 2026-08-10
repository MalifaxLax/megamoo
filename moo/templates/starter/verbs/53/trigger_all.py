"""
trigger_all verb on #53 (effects_utils).

Triggers multiple effects on a target character at once. Processes
a list of effect tuples and registers each one. Delegates to the
Python EffectsManager.

Method-call interface: $eu.trigger_all(target, effects_list)

Arguments (via _pyargs):
    target       - The character object to apply effects to.
    effects_list - List of effect tuples to trigger.

Hidden:  yes
"""

result = _effects.trigger_all(*_pyargs)
