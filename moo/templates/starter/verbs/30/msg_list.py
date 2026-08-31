"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

def msg_list(string, targ_list, exclude=None):
        """
        Send a message string to every object in a target list.

        This is a convenience wrapper around the ``notify`` builtin that
        handles iteration and exclusion.  Commonly used for room-wide
        messages where the acting player should be excluded.

        Args:
            string (str): The message text to send.
            targ_list (list): List of MOOObject instances to notify.
            exclude (MOOObject or list, optional): Object(s) to skip.
                Can be a single object or a list.  ``None`` means
                no exclusions.

        Example::

            su.msg_list("Gandalf leaves north.", room.contents, exclude=player)
        """
        if not isinstance(exclude, list):
            exclude = [exclude] if exclude else []
        from .builtins import notify
        for obj in targ_list:
            if obj not in exclude:
                notify(obj, string)


_a = kwargs.pop('_pyargs', None)

return msg_list(*(_a if _a is not None else argv), **kwargs)
