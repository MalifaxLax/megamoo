# do_wait on #5 (ICharacter)
# Returns True if the character cannot act (status/condition/RT check).
# Usage: call_verb(pobj, 'do_wait')

_status = getattr(this, 'status', None) or {}
_condition = getattr(this, 'condition', None) or {}

if _status.get('unconscious', 0):
    this.msg('You are unconscious...')
    result = True
elif _status.get('sleeping', 0):
    this.msg('You are sleeping...')
    result = True
elif _status.get('paralyzed', 0):
    this.msg('You are paralyzed...')
    result = True
elif _condition.get('webbed', 0):
    this.msg('You are webbed...')
    result = True
elif _condition.get('immobilized', 0):
    this.msg('You are immobilized...')
    result = True
elif _condition.get('entangled', 0):
    this.msg('You are entangled...')
    result = True
elif _condition.get('imprisoned', 0):
    this.msg('You are imprisoned...')
    result = True
elif _condition.get('bound', 0):
    this.msg('You are tied up...')
    result = True
elif _status.get('life', 0) and not _status.get('stunned', 0):
    _rt = getattr(this, 'rt', 0) or 0
    if _rt > 0:
        this.msg(f'[Wait: {_rt} seconds]')
        result = True
    else:
        result = False
else:
    result = False
