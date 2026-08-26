"""
make_object on $obj_utils.

Ported from `moo.object_utils` by tools/port_to_verbs.py.  The function is carried
verbatim rather than rewritten, so the behaviour is identical by
construction; tools/equivalence.py checks that against the original.

Type:    function
"""

from typing import TYPE_CHECKING, Optional

def _call_title(obj: 'MOOObject', db: 'Database', pobj: 'MOOObject'):
    """
    Call the ``_title`` verb on *obj* to rebuild its display name.

    The ``_title`` verb constructs ``obj.name`` from the object's noun
    and name_mod_list.  This function first tries to
    invoke ``_title`` via the verb execution system (using ``call_verb``
    from the active verb context).  If no verb context is available
    (e.g. during bootstrap or direct script calls), it falls back to
    :func:`_inline_title` which implements the same logic directly.

    Args:
        obj:  The object whose title needs to be rebuilt.
        db:   The database instance.
        pobj: The player object (needed for verb execution context).
    """
    try:
        from .verb_context import verb_ctx
        ctx = verb_ctx.get(None)
        if ctx:
            from .builtins import make_call_verb
            call_verb = make_call_verb(pobj, db, ctx[2])
            call_verb(obj, '_title')
            return
    except Exception:
        pass

    # Fallback: inline the _title logic if no verb context is available
    _inline_title(obj)

def _set_property(obj: 'MOOObject', prop_name: str, value):
    """
    Set a property on *obj*, creating it if it does not exist locally.

    If the property already exists on the object, its value is updated
    in place.  Otherwise, a new property is added with default
    permissions ``'rc'`` (readable, inheritable).

    The object is marked as modified after the change so it will be
    saved to the database on the next save cycle.

    Args:
        obj:       The object to set the property on.
        prop_name: Name of the property.
        value:     The value to set (any Python type).
    """
    if prop_name in obj.properties:
        obj.properties[prop_name].value = value
    else:
        obj.add_property(prop_name, value, perms='rc')
    obj._mark_modified()

def _inline_title(obj: 'MOOObject'):
    """
    Inline fallback for ``_title`` when no verb execution context
    is available (e.g. during bootstrap, migration, or direct script
    calls).

    Builds the display name from the object's noun and name_mod_list:

    1. Reads name_mod_list: ``[article, adj1, adj2, adj3, trailer]``
    2. Auto-corrects "a"/"an" based on the first letter of the next word
    3. Joins non-empty parts with spaces
    4. Appends the trailer (e.g. "(broken)") if present
    5. Sets ``obj.name`` and updates name_mod_list

    Args:
        obj: The object whose title needs to be rebuilt.
    """
    # Read the name_mod_list from local properties
    nml_val = None
    if 'name_mod_list' in obj.properties:
        nml_val = obj.properties['name_mod_list'].value

    # Ensure nml is always a 5-element list
    if nml_val:
        nml = list(nml_val)
        while len(nml) < 5:
            nml.append('')
    else:
        nml = ['', '', '', '', '']

    # Decompose the name_mod_list
    article = (nml[0] or '').strip()
    adjs = [a.strip() for a in nml[1:4] if a and a.strip()]
    trailer = (nml[4] or '').strip()
    noun = (obj.noun or '').strip()

    # Auto-correct a/an based on the first letter of the next word
    if article.lower() in ('a', 'an'):
        first_word = adjs[0] if adjs else noun
        if first_word and first_word[0].lower() in 'aeiou':
            article = 'an' if article[0].islower() else 'An'
        else:
            article = 'a' if article[0].islower() else 'A'
        nml[0] = article

    # Build the display name: "a rusty old sword"
    parts = [p for p in [article] + adjs + [noun] if p]
    name = ' '.join(parts)
    if trailer:
        name = f'{name} {trailer}'

    # Update the object
    obj.name = name
    _set_property(obj, 'name_mod_list', nml)

def _get_property_value(obj: 'MOOObject', prop_name: str, db: 'Database' = None):
    """
    Get a property value from *obj*, walking the inheritance chain.

    Checks the object's local properties first.  If the property is not
    found locally, walks up the parent chain (using the database to
    resolve parent object numbers) until the property is found or the
    chain is exhausted.

    Circular parent references are detected and avoided via a visited
    set.

    Args:
        obj:       The object to read the property from.
        prop_name: Name of the property to look up.
        db:        Database instance for resolving parent objects.
                   If ``None``, attempts to get the database from the
                   active verb context.

    Returns:
        The property value, or ``None`` if not found anywhere in the
        inheritance chain.
    """
    # Check local properties first (fast path)
    if prop_name in obj.properties:
        return obj.properties[prop_name].value

    # If no database was provided, try to get one from the verb context
    if db is None:
        try:
            from .verb_context import verb_ctx
            ctx = verb_ctx.get(None)
            if ctx:
                db = ctx[1]
        except Exception:
            pass

    # Walk the parent chain looking for an inherited property
    if db is not None:
        parent_num = obj.parent
        visited = {obj.objnum}  # Track visited objects to prevent cycles
        while parent_num and parent_num not in visited:
            visited.add(parent_num)
            try:
                parent_obj = db.get_object(parent_num)
            except (KeyError, Exception):
                break
            if prop_name in parent_obj.properties:
                return parent_obj.properties[prop_name].value
            parent_num = parent_obj.parent

    return None



def make_object(parent: 'MOOObject', db: 'Database', pobj: 'MOOObject',
                noun: Optional[str] = None,
                owner: Optional['MOOObject'] = None) -> 'MOOObject':
    """
    Create a new object as a child of *parent*.

    This is the primary factory function for creating game objects
    (items, NPCs, containers, etc.).  It handles:

    1. Creating the object in the database with proper parent/owner.
    2. Copying the ``name_mod_list`` from the parent (inherits article).
    3. Setting the noun (either the given *noun* or the parent's noun).
    4. Calling ``_title`` to build the display name.
    5. Firing the ``object_creation`` hook.

    If *noun* is given, it becomes the new object's noun and the
    ``name_mod_list`` is copied from the parent.  If *noun* is ``None``,
    both the noun and ``name_mod_list`` are copied from the parent
    unchanged.

    Args:
        parent: The parent object to inherit from (determines the
                object's type and default properties).
        db:     The database instance.
        pobj:   The player creating the object (verb execution context).
        noun:   Optional noun for the new object.  If omitted, the
                parent's noun and name_mod_list are used as-is.
        owner:  Optional owner object.  Defaults to *pobj*.

    Returns:
        The newly created MOOObject, with name and title fully set up.

    Examples::

        # Create a sword from the object prototype (#9)
        sword = make_object(db.get_object(9), db, pobj, noun='sword')

        # Create a copy with the same name as the parent
        clone = make_object(db.get_object(9), db, pobj)

        # Create with a different owner
        gift = make_object(parent, db, pobj, noun='gift', owner=recipient)
    """
    owner_obj = owner or pobj
    new_obj = db.create_object(parent=parent.objnum, owner=owner_obj.objnum)

    # Copy name_mod_list from parent, defaulting to ['a', '', '', '', '']
    parent_nml = _get_property_value(parent, 'name_mod_list', db)
    if parent_nml is not None:
        nml = list(parent_nml)
    else:
        nml = ['a', '', '', '', '']

    # Set the noun -- either the provided noun or the parent's noun
    if noun is not None:
        new_obj.noun = noun
    else:
        new_obj.noun = parent.noun

    _set_property(new_obj, 'name_mod_list', nml)

    # Call _title to build the display name from noun + name_mod_list
    _call_title(new_obj, db, pobj)

    # Fire the object_creation hook
    from moo.hooks import fire_hook
    fire_hook('object_creation', new_obj)

    return new_obj


_a = kwargs.pop('_pyargs', None)

return make_object(*(_a if _a is not None else argv), **kwargs)
