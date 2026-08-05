

def test_a_declared_but_unset_property_is_carried():
    """
    MOO's clear value means two different things and the importer has to
    tell them apart.

    On a slot an object *inherits*, clear means "I do not override this",
    and an absent MegaMOO property already says that -- writing one would
    turn an inherited value into a local None.

    On a property the object *declares itself*, clear means "this exists
    here and is unset", which is ordinary: @show lists it and reading it
    gives none rather than E_PROPNF.  Skipping those lost 716 properties
    across JHCore, including $module, $mcp and $local, which #0 declares
    and leaves unset -- and after the E_PROPNF change, reading one raised
    instead of returning nothing.
    """
    from moo.lambdamoo import LambdaObject
    from moo.lambdamoo_import import property_names_for

    o = LambdaObject(objid=0, name='System Object', parent=-1)
    o.propdefs = ['declared_unset']
    o.propvals = [(None, 2, 0)]
    # names come from the object's own propdefs when it has no ancestors
    assert 'declared_unset' in property_names_for(o, _Stub([o]))
    assert 'declared_unset' in o.propdefs


class _Stub:
    """Minimal LambdaDB stand-in: property_names_for only walks parents."""

    def __init__(self, objs):
        self.objects = {o.objid: o for o in objs}
        self.live_objects = objs
