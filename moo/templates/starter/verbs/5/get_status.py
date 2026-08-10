"""
get_status verb on #5 (ICharacter).

Returns a dictionary of the character's active status effects. Includes
statuses like unconscious, sleeping, stunned, paralyzed, etc. The 'life'
status is only included when its value is 0 (i.e., the character is dead).

Called programmatically: call_verb(char, 'get_status')

Returns:
    dict - {status_name: value} for active statuses. Life is included
           only when it equals 0 (dead).

Hidden:  yes
"""

return {k: v for k, v in this.status.items()
        if (v > 0 and k != 'life') or (k == 'life' and v == 0)}
