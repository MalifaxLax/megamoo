"""
Ported verbatim from moo.moo_libs; tools/equivalence.py checks it.

Type:    function
"""

from typing import Any, List, Optional



def slice(alist: List, index: Any = 1) -> List:
        """
        The *index*-th element of each element of *alist*.

        JHCore: ``slice({{"z",1},{"y",2},{"x",5}},2) => {1,2,5}``.  *index*
        may also be a list, which reorders: ``slice({{"z",1,3}},{2,1})``
        gives ``{{1,"z"}}``.
        """
        out = []
        for elt in alist or []:
            if isinstance(index, (list, tuple)):
                out.append([elt[i - 1] for i in index])
            else:
                out.append(elt[index - 1])
        return out


_a = kwargs.pop('_pyargs', None)

return slice(*(_a if _a is not None else argv), **kwargs)
