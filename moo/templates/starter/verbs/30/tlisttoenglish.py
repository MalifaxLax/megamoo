"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

def tlisttoenglish(targlist):
        """
        Join a list of game objects into an English phrase using their names.

        Like :meth:`listtoenglish` but extracts ``obj.name`` from each
        element first.  ``None`` entries in the list are silently skipped.

        Args:
            targlist (list of MOOObject): Objects whose names to join.

        Returns:
            str: A human-readable phrase of object names.

        Example::

            su.tlisttoenglish([sword_obj, shield_obj])
            # => "a sword and a shield"
        """
        names = [obj.name for obj in targlist if obj]
        return call_verb(this, 'listtoenglish', names)


_a = kwargs.pop('_pyargs', None)

return tlisttoenglish(*(_a if _a is not None else argv), **kwargs)
