"""
eat_ verb on #91 (BaseDrinkable).

Prevents eating liquid items. Returns True with a "You can't eat that"
message so the eat command does not fall through to other handlers.

Hidden:  yes
"""

pobj.msg("You can't eat that.")
return True
