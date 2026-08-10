"""
move verb on #21 (DirectionalExit).

Simple wrapper that delegates to the gmove verb to perform the actual
player movement through this exit.

Called programmatically: call_verb(exit, 'move')

Hidden:  yes
"""
call_verb(this, 'gmove')
