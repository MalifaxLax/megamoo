"""
Reserved hook on #3 (Base_Character).  Does nothing.

The body is empty and nothing in either verb tree calls it, so it runs
only if something reaches it by name.  It is kept because removing a
verb from a base object is not free -- a descendant may define its own
`_allow` expecting this to be the thing it overrides -- and because the
name suggests a permission check that was planned and not written.

Hidden, so the parser will not dispatch it; call_verb still can.

Hidden:  yes
"""
