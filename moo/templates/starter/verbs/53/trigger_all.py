"""
trigger_all on $effects_utils.

Ported from `moo.effects` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def trigger_all(pobj, effects_list):
        """
        Trigger multiple effects from a list of tuples.

        Convenience method for applying a batch of effects at once,
        e.g. from a stored "effect loadout" on an item or area.

        Each element of *effects_list* should be a tuple or list of
        the form::

            (name, ticks, interval, *extra_args)

        Args:
            pobj: Target MOOObject to apply the effects to.
            effects_list: Iterable of tuples/lists, each containing
                the arguments for a single ``trigger()`` call.

        Raises:
            TypeError: If any element of *effects_list* is not a
                tuple or list.
        """
        for effect in effects_list:
            if isinstance(effect, (list, tuple)):
                # Unpack the tuple as positional args to trigger()
                call_verb(this, 'trigger', pobj, *effect)
            else:
                raise TypeError(f"Expected tuple/list, got {type(effect)}")


_a = kwargs.pop('_pyargs', None)

return trigger_all(*(_a if _a is not None else argv), **kwargs)
