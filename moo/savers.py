"""
Lists and dicts read from a property that write themselves back.

``obj.wear_list.insert(0, [])`` used to do nothing at all.  Reading a
list-valued property hands back a *new* container, because the stored form
and the read form are not the same thing -- an objref is stored as ``'#5'``
and resolved to a live object on the way out -- so the comprehension in
``_resolve_objref`` has to build something. Mutating that something
mutated a copy, and the copy was discarded. Nothing raised; the change
simply never happened, which is the worst way for an interactive prompt to
behave.

The fix is not to stop copying. The copy is load-bearing twice over:

* Stored and read differ, as above.
* A property may be *inherited*. ``#5`` declares no ``wear_list``; it reads
  ``#3``'s. Handing back the stored list would mean ``#5.wear_list.insert``
  edited the prototype, changing it for every character in the game.

So the copy stays and learns where it came from. A ``SaverList`` knows the
object and property it was read from, and any mutation writes the whole
container back through ordinary attribute assignment -- which serialises
objrefs again, marks the property dirty, and on an inherited read creates a
*local* property on the reader rather than touching the parent. That last
part is copy-on-write, and it is the behaviour a builder expects.

Cost: a mutation rewrites the whole property, so a thousand appends in a
loop is a thousand writes. Build a plain list and assign it once if that
matters. Reads are no more expensive than before -- the copy was already
being made; this only gives it a back-reference.

One wrinkle these classes cannot solve themselves: ``type(x) == list`` is
False for a subclass, while ``isinstance(x, list)`` is True. The verb and
eval namespaces therefore install a ``type()`` that answers ``list`` for a
SaverList and ``dict`` for a SaverDict, so verb code sees the plain kind it
is standing in for. That also makes ``type()`` agree with MOO's own
``typeof()``, which already reports ``LIST`` because it asks with
``isinstance``.
"""

__all__ = ['SaverList', 'SaverDict', 'is_saver', 'plain']


class _SaverBase:
    """Shared write-back plumbing for the two container types.

    Slots live on the concrete classes, not here: a mixin that declares
    instance layout cannot be combined with ``list`` or ``dict``, which
    declare their own ("multiple bases have instance lay-out conflict").
    """

    __slots__ = ()

    def _bind(self, owner, prop, root):
        # object.__setattr__ rather than plain assignment: list and dict
        # subclasses with __slots__ still route attribute writes normally,
        # but being explicit here keeps a future __setattr__ override on
        # these classes from swallowing its own bookkeeping.
        object.__setattr__(self, '_owner', owner)
        object.__setattr__(self, '_prop', prop)
        object.__setattr__(self, '_root', root if root is not None else self)
        return self

    def _save(self):
        """Write the outermost container back to the property it came from.

        Always the root, never ``self``: ``obj.d['a'].append(x)`` mutates an
        inner list, and what has to be stored is the whole of ``obj.d``.
        """
        root = getattr(self, '_root', None)
        if root is None:
            return
        owner = getattr(root, '_owner', None)
        prop = getattr(root, '_prop', None)
        if owner is None or not prop:
            return
        # Ordinary attribute assignment, which is the unchecked write path --
        # the same one `obj.prop = value` has always used. A saver must not
        # be more restrictive than the assignment it stands in for.
        setattr(owner, prop, root)


def _mutator(name):
    """Wrap a mutating method so it saves after it succeeds."""
    def method(self, *args, **kwargs):
        result = getattr(self._base, name)(self, *args, **kwargs)
        self._save()
        return result
    method.__name__ = name
    method.__qualname__ = name
    method.__doc__ = f'As {name}(), then writes the property back.'
    return method


class SaverList(list, _SaverBase):
    """A list read from a property. Mutating it stores the change."""

    __slots__ = ('_owner', '_prop', '_root')
    _base = list

    #: Every list method that changes the contents. ``__iadd__`` and
    #: ``__imul__`` are here so ``x += [1]`` persists; slice assignment and
    #: ``del x[0]`` arrive through ``__setitem__`` / ``__delitem__``.
    _MUTATORS = ('append', 'insert', 'extend', 'pop', 'remove', 'clear',
                 'sort', 'reverse', '__setitem__', '__delitem__',
                 '__iadd__', '__imul__')

    for _name in _MUTATORS:
        locals()[_name] = _mutator(_name)
    del _name


class SaverDict(dict, _SaverBase):
    """A dict read from a property. Mutating it stores the change."""

    __slots__ = ('_owner', '_prop', '_root')
    _base = dict

    _MUTATORS = ('__setitem__', '__delitem__', 'update', 'setdefault',
                 'pop', 'popitem', 'clear', '__ior__')

    for _name in _MUTATORS:
        locals()[_name] = _mutator(_name)
    del _name


def is_saver(value):
    """Whether *value* is one of the write-back containers."""
    return isinstance(value, (SaverList, SaverDict))


def plain(value):
    """*value* as an ordinary list/dict, recursively -- no back-references.

    For anywhere a saver must not travel: a return value handed to
    something that stores it, or a snapshot taken before a change.
    """
    if isinstance(value, (SaverList, list)):
        return [plain(v) for v in value]
    if isinstance(value, (SaverDict, dict)):
        return {k: plain(v) for k, v in value.items()}
    return value
