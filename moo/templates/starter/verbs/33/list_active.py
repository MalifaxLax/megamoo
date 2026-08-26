"""
list_active on $effects_utils.

Ported from `moo.effects` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

def list_active(pobj):
        """
        Return a list of active effects on a target object.

        Useful for displaying status information to the player
        (e.g. a "status effects" panel) or for game logic that
        checks whether a specific effect is active.

        Args:
            pobj: Target MOOObject to query.

        Returns:
            List[dict]: A list of dictionaries, each with keys:
                - ``'name'`` (str): Effect name.
                - ``'remaining'`` (int): Number of fires left.
                - ``'tick'`` (int): Number of times fired so far.
                - ``'interval'`` (float): Seconds between fires.
                Returns an empty list if no effects are active.
        """
        eu_obj = this

        # Read the current registry
        registry = eu_obj.fx_registry or {}
        if not isinstance(registry, dict):
            return []

        # Filter to entries matching the target object
        results = []
        for entry in registry.values():
            if entry['objnum'] == pobj.objnum:
                results.append({
                    'name': entry['name'],
                    'remaining': entry['remaining'],
                    'tick': entry['tick'],
                    'interval': entry['interval'],
                })
        return results


_a = kwargs.pop('_pyargs', None)

return list_active(*(_a if _a is not None else argv), **kwargs)
