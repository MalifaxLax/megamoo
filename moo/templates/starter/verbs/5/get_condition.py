"""
get_condition verb on #5 (ICharacter).

Returns a dictionary of the character's active conditions (those with a
value greater than zero). Conditions include things like webbed, immobilized,
entangled, imprisoned, and bound.

Called programmatically: call_verb(char, 'get_condition')

Returns:
    dict - {condition_name: value} for all conditions where value > 0.

Hidden:  yes
"""

return {k: v for k, v in this.condition.items() if v > 0}
