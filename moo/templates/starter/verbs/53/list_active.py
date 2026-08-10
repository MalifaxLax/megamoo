"""
list_active verb on #53 (effects_utils).

Returns a list of currently active effects on the target character.
Delegates to the Python EffectsManager.

Method-call interface: $eu.list_active(target)

Arguments (via _pyargs):
    target - The character object to query.

Returns:
    list - Active effect names/entries on the target.

Hidden:  yes
"""

result = _effects.list_active(*_pyargs)
