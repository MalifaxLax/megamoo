#!/usr/bin/env python3
"""Give every starter object a name that survives renumbering and renaming.

An upgrade has to pair the object in a world with the object it came from in
the starter.  Matching by number fails the moment either side renumbers --
which the starter did once, at b17, when 75 numbers changed hands.  Matching
by noun fails the moment a builder renames something, which is an ordinary
thing to do to your own world.

So each starter object carries a `template_key`: set once, never derived
from anything the builder can change, and copied into every world by
`megamoo init` along with the object itself.

Every object gets one, not the handful that happen to be parents today.
In Shadowfall, builder-created objects are parented to twenty-odd starter
objects including `item`, `table`, `pants` and `shoes` -- leaves in the
shipped world, prototypes in a real one.  Which objects turn out to matter
is not knowable in advance, and a key costs nothing.

Usage:
    python tools/stamp_template_keys.py [--check] [<world.db>]
"""
import argparse
import collections
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STARTER = os.path.join(os.path.dirname(HERE), 'moo', 'templates', 'starter',
                       'world.db')
PROP = 'template_key'


def next_keys(existing, needed):
    """Opaque keys for objects that have none.

    A backfill only.  Objects created from b23 onward are stamped by
    create_object, and this uses the same generator so the two shapes
    cannot drift apart.
    """
    sys.path.insert(0, os.path.dirname(HERE))
    from moo.globals import new_template_key
    used = set(existing.values())
    out = {}
    for objnum in needed:
        key = new_template_key()
        while key in used:
            key = new_template_key()
        used.add(key)
        out[objnum] = key
    return out


def stamp(db_path, check=False):
    con = sqlite3.connect('file:%s?mode=ro' % db_path if check else db_path,
                          uri=check)
    rows = list(con.execute('select objnum,noun,parent from objects'))
    have = {o: json.loads(v) for o, v in con.execute(
        'select objnum,value from properties where name=?', (PROP,))}
    missing = [o for o, _, _ in rows if o not in have]

    dupes = [k for k, n in collections.Counter(have.values()).items() if n > 1]

    if check:
        con.close()
        return {'total': len(rows), 'missing': missing, 'dupes': dupes,
                'unique': not dupes}

    # Append-only.  An existing key is never recomputed: something in the
    # field may already be paired by it, and a key that changes is not one.
    fresh = next_keys(have, missing)
    for objnum, key in fresh.items():
        con.execute(
            'insert or replace into properties (objnum,name,value,owner,perms)'
            ' values (?,?,?,?,?)',
            (objnum, PROP, json.dumps(key), 0, 'r'))
    con.commit()
    con.close()
    return {'total': len(rows), 'stamped': len(fresh),
            'kept': len(have), 'unique': not dupes}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('world', nargs='?', default=STARTER)
    ap.add_argument('--check', action='store_true',
                    help='report without writing')
    a = ap.parse_args()

    r = stamp(a.world, check=a.check)
    if a.check:
        print('%s' % a.world)
        print('  objects            : %d' % r['total'])
        print('  without a key      : %d' % len(r['missing']))
        print('  duplicated keys    : %s' % (r['dupes'] or 'none'))
        return 0 if not r['missing'] and r['unique'] else 1
    print('stamped %d new, kept %d existing (unique: %s)'
          % (r['stamped'], r['kept'], r['unique']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
