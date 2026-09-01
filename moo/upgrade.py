"""Tell a world what the starter has learned since it was created.

A world is copied out of the starter by ``megamoo init`` and belongs to its
builder from that moment.  That is the right bargain -- nobody wants an
engine reaching into their game -- but it has meant improvements to the
starter never reach a world that already exists.  Every fix, forever, only
helps worlds created after it.

The obstacle was never merging.  It was that nothing could tell "the builder
edited this" apart from "this is what the starter always shipped".  A world
records the version it was born from (``template_version``), and the engine
ships a manifest of hashes for every released version, so that question is
answerable per item:

    ================  ================  ==========================
    since birth       upstream          verdict
    ================  ================  ==========================
    unchanged         changed           update -- safe
    changed           changed           conflict -- report, leave
    changed           unchanged         local -- leave
    absent            added             add -- safe
    unchanged         removed           removable -- offer
    ================  ================  ==========================

":func:`plan` reports and writes nothing.  :func:`apply` acts on the safe
half of a plan -- updates, additions and provable removals -- and refuses
outright if a server has the world open.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import sqlite3
from typing import Dict, List, Optional

MANIFEST_CHAIN = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'templates', 'manifests', 'chain.json.gz')
STARTER_WORLD = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             'templates', 'starter', 'world.db')

UPDATE, CONFLICT, LOCAL, ADD, REMOVABLE, GONE = (
    'update', 'conflict', 'local', 'add', 'removable', 'deleted-locally')


def _h(text: str, n: int) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:n]


def load_chain(path: str = MANIFEST_CHAIN) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    with gzip.open(path, 'rb') as fh:
        return json.loads(fh.read().decode('utf-8'))


def replay(chain: dict, version: str) -> Optional[dict]:
    """The manifest for *version*, rebuilt from base plus deltas."""
    if version not in chain['versions']:
        return None
    man = json.loads(json.dumps(chain['full']))
    if version == chain['base']:
        return man
    for v in chain['versions'][1:]:
        d = chain['deltas'].get(v, {})
        for section, items in d.get('changed', {}).items():
            man[section].update(items)
        for section, keys in d.get('removed', {}).items():
            for k in keys:
                man[section].pop(k, None)
        if v == version:
            break
    return man


def _read_verbs(db_path: str, hash_len: int) -> Dict[str, dict]:
    con = sqlite3.connect('file:%s?mode=ro' % db_path, uri=True)
    out = {}
    for objnum, names, code, perms, ptype, minl, hidden in con.execute(
            'select objnum,names,code,perms,parent_type,min_lengths,hidden '
            'from verbs'):
        primary = json.loads(names)[0]
        meta = json.dumps([json.loads(names), perms, ptype,
                           json.loads(minl or '{}'), bool(hidden)],
                          sort_keys=True)
        out['%d:%s' % (objnum, primary)] = {
            'code': _h(code, hash_len), 'meta': _h(meta, hash_len)}
    con.close()
    return out


def _read_objects(db_path: str) -> Dict[str, dict]:
    con = sqlite3.connect('file:%s?mode=ro' % db_path, uri=True)
    tkeys = {o: json.loads(v) for o, v in con.execute(
        "select objnum,value from properties where name='template_key'")}
    out = {}
    for o, p, n in con.execute('select objnum,parent,noun from objects'):
        rec = {'parent': p, 'noun': n}
        if o in tkeys:
            rec['key'] = tkeys[o]
        out[str(o)] = rec
    con.close()
    return out


def _comparable(objects: Dict[str, dict]) -> Dict[str, dict]:
    """Just what an object *is*, for comparison.

    Never the key and never the number.  Both identify the object rather
    than describe it, and including either makes an object differ from
    itself -- the key because a manifest predating it has none, the number
    because a renumbered object has a new one.
    """
    return {num: {'parent': rec.get('parent'), 'noun': rec.get('noun')}
            for num, rec in objects.items()}


def _by_key_parents(objects: Dict[str, dict]) -> Dict[str, dict]:
    """Re-express each object's parent as the parent's key, not its number.

    Otherwise a world that renumbered a prototype reports every child of it
    as locally changed -- the child is identical, and only the number it
    names its parent by has moved.
    """
    keys = {num: r['key'] for num, r in objects.items() if 'key' in r}
    out = {}
    for num, rec in objects.items():
        r = dict(rec)
        r['parent'] = keys.get(str(rec.get('parent')), rec.get('parent'))
        out[num] = r
    return out


def _rekey(objects: Dict[str, dict]) -> Dict[str, dict]:
    """Re-index objects by template_key where they have one.

    Pairing by number breaks across a renumber; pairing by noun breaks when
    a builder renames their own object, which is an ordinary thing to do.
    The key is set once by the starter and changed by nothing, so where both
    sides carry one it is the only honest way to say "these are the same
    object".  Objects without a key keep their number as the key, which is
    what worlds older than the stamp fall back to.
    """
    out = {}
    for num, rec in objects.items():
        # Only what identifies the object, never the number: including the
        # number makes every renumbered object differ from itself.
        out[rec['key'] if 'key' in rec else '#' + num] = {
            'parent': rec.get('parent'), 'noun': rec.get('noun')}
    return out


def keyed(objects: Dict[str, dict]) -> bool:
    """Whether this collection carries template keys at all."""
    return any('key' in r for r in objects.values())


def _read_props(db_path: str, hash_len: int) -> Dict[str, str]:
    con = sqlite3.connect('file:%s?mode=ro' % db_path, uri=True)
    out = {'%d:%s' % (o, n): _h('%s\x00%s' % (v, pm), hash_len)
           for o, n, v, pm in con.execute(
               'select objnum,name,value,perms from properties')}
    con.close()
    return out


def _classify(base, theirs, new):
    """The same five verdicts, for any keyed collection."""
    items = []
    for key in sorted(set(base) | set(theirs) | set(new)):
        in_b, in_t, in_n = key in base, key in theirs, key in new
        if in_t and in_n and in_b:
            untouched = theirs[key] == base[key]
            moved = new[key] != base[key]
            if untouched and moved:
                items.append((UPDATE, key, 'changed upstream'))
            elif not untouched and moved:
                items.append((CONFLICT, key, 'both changed'))
            elif not untouched:
                items.append((LOCAL, key, 'yours'))
        elif in_n and not in_t:
            items.append((ADD, key,
                          'new upstream' if not in_b else 'you deleted it'))
        elif in_t and not in_n and in_b:
            items.append((REMOVABLE, key, 'dropped upstream')
                         if theirs[key] == base[key]
                         else (LOCAL, key, 'yours, dropped upstream'))
        elif in_b and not in_t and not in_n:
            items.append((GONE, key, 'gone both sides'))
    return items


def world_template_version(db_path: str) -> Optional[str]:
    con = sqlite3.connect('file:%s?mode=ro' % db_path, uri=True)
    try:
        row = con.execute(
            "select value from metadata where key='template_version'"
        ).fetchone()
    except sqlite3.DatabaseError:
        return None
    finally:
        con.close()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except (ValueError, TypeError):
        return row[0]


IGNORE_PROP = 'upgrade_ignore'


def _ignored(world_db: str):
    """Keys this world has declined, from #0.upgrade_ignore.

    A world that arrived at the starter's numbering from its own history --
    rather than by being copied out of it -- shares a great deal and
    deliberately differs elsewhere.  Shadowfall routes afflictions through
    #1:_afflict instead of $eu's do_* handlers, and keeps do_wait on #5
    rather than #3.  Those are not omissions to be repaired; offering them
    at every upgrade forever would be noise, and taking them would be wrong.

    Entries are the same keys the plan reports -- '33:do_stun', '#101',
    '5:status' -- and an entry only ever suppresses an *addition*.  Nothing
    here can stop a conflict being reported: declining something you do not
    want is not the same as hiding a collision with something you do.
    """
    con = sqlite3.connect('file:%s?mode=ro' % world_db, uri=True)
    try:
        row = con.execute(
            "select value from properties where objnum=0 and name=?",
            (IGNORE_PROP,)).fetchone()
    except sqlite3.DatabaseError:
        return set()
    finally:
        con.close()
    if not row:
        return set()
    try:
        return set(json.loads(row[0]) or [])
    except (ValueError, TypeError):
        return set()


def plan(world_db: str, starter_db: str = STARTER_WORLD,
         chain_path: str = MANIFEST_CHAIN) -> dict:
    """What an upgrade would do to *world_db*.  Reads only."""
    born = world_template_version(world_db)
    chain = load_chain(chain_path)
    result = {'world': world_db, 'born': born, 'items': [], 'objects': [],
              'properties': [], 'error': None, 'paired_by': None}

    if chain is None:
        result['error'] = 'no manifest chain shipped with this engine'
        return result
    if born is None:
        result['error'] = ('world has no template_version -- it predates the '
                           'stamp, so what it started from is unknown')
        return result

    base = replay(chain, born)
    if base is None:
        result['error'] = ('no manifest for %s; known versions are %s..%s'
                           % (born, chain['versions'][0], chain['versions'][-1]))
        return result

    hl = chain['hash_len']
    new_objects = _read_objects(starter_db)
    world_objects = _read_objects(world_db)

    # Pair on identity where every side has it.  template_key is assigned at
    # creation and changed by nothing, so it is the only spelling of "these
    # are the same object" that survives both a renumber and a rename.
    xlate = {}
    base_xlate = {}
    if keyed(base['objects']) and keyed(world_objects) and keyed(new_objects):
        result['paired_by'] = 'identity'
        world_by_key = {r['key']: num for num, r in world_objects.items()
                        if 'key' in r}
        # Both the starter and the manifest speak the starter's numbering;
        # only the world speaks its own.  So both get translated into it,
        # not just the starter -- translating one and not the other reads
        # every renumbered object's verbs as deleted here and added there.
        for num, rec in new_objects.items():
            here = world_by_key.get(rec.get('key'))
            if here is not None and here != num:
                xlate[num] = here
        for num, rec in base['objects'].items():
            here = world_by_key.get(rec.get('key'))
            if here is not None and here != num:
                base_xlate[num] = here
        result['objects'] = _classify(
            _rekey(_by_key_parents(base['objects'])),
            _rekey(_by_key_parents(world_objects)),
            _rekey(_by_key_parents(new_objects)))
    else:
        # No keys on one side or another -- a world older than the stamp.
        # Fall back to the number, which holds only while nothing has been
        # renumbered.  An object number that now carries a different object
        # is not an update, it is a different object: the starter was
        # renumbered at b17 and 75 numbers changed hands, and reconciling
        # such a world by number would rewrite its rooms into unrelated
        # prototypes.  The test is for the condition, not for b17.
        result['paired_by'] = 'number'
        renamed = sorted(
            (k for k in set(base['objects']) & set(new_objects)
             if base['objects'][k]['noun'] != new_objects[k]['noun']),
            key=int)
        if renamed:
            result['error'] = (
                'object numbers were reassigned between %s and the current '
                'starter -- %d of them, including #%s. This world predates '
                'template_key, so there is nothing to pair on but the number, '
                'and those numbers hold different objects now. Verb files can '
                'still be carried across by hand.'
                % (born, len(renamed), ', #'.join(renamed[:4])))
            return result
        result['objects'] = _classify(_comparable(base['objects']),
                                      _comparable(world_objects),
                                      _comparable(new_objects))

    def _tr(keyed_map, m=None):
        """Starter numbering -> this world's, for `N:name` keys."""
        m = xlate if m is None else m
        if not m:
            return keyed_map
        out = {}
        for k, v in keyed_map.items():
            num, _, rest = k.partition(':')
            out['%s:%s' % (m.get(num, num), rest)] = v
        return out

    result['properties'] = _classify(_tr(base['properties'], base_xlate),
                                     _read_props(world_db, hl),
                                     _tr(_read_props(starter_db, hl)))
    theirs = _read_verbs(world_db, hl)
    new = _tr(_read_verbs(starter_db, hl))
    b = _tr(base['verbs'], base_xlate)

    for key in sorted(set(b) | set(theirs) | set(new)):
        in_b, in_t, in_n = key in b, key in theirs, key in new
        if in_t and in_n and in_b:
            untouched = theirs[key] == b[key]
            upstream_moved = new[key] != b[key]
            if untouched and upstream_moved:
                what = 'code' if new[key]['code'] != b[key]['code'] else 'metadata'
                result['items'].append((UPDATE, key, what))
            elif not untouched and upstream_moved:
                result['items'].append((CONFLICT, key, 'both changed'))
            elif not untouched:
                result['items'].append((LOCAL, key, 'yours'))
        elif in_n and not in_t:
            result['items'].append(
                (ADD, key, 'new upstream' if not in_b else 'you deleted it'))
        elif in_t and not in_n and in_b:
            if theirs[key] == b[key]:
                result['items'].append((REMOVABLE, key, 'dropped upstream'))
            else:
                result['items'].append((LOCAL, key, 'yours, dropped upstream'))
        elif in_b and not in_t and not in_n:
            result['items'].append((GONE, key, 'gone both sides'))

    declined = _ignored(world_db)
    if declined:
        for kind in ('items', 'objects', 'properties'):
            result[kind] = [(v, k, w) for v, k, w in result[kind]
                            if not (v == ADD and k in declined)]
        result['declined'] = len(declined)

    return result


def summarise(p: dict) -> List[str]:
    """The plan as lines a person can read."""
    if p['error']:
        return ['Cannot plan an upgrade: %s' % p['error']]
    counts: Dict[str, int] = {}
    for verdict, _, _ in p['items']:
        counts[verdict] = counts.get(verdict, 0) + 1

    lines = ['World born from %s.' % p['born'], '']
    order = [(UPDATE, 'can be updated -- untouched here, changed upstream'),
             (ADD, 'can be added -- new upstream'),
             (CONFLICT, 'CONFLICT -- you changed these and so did upstream'),
             (REMOVABLE, 'dropped upstream, untouched here'),
             (LOCAL, 'yours -- left alone'),
             (GONE, 'gone from both')]
    for verdict, label in order:
        n = counts.get(verdict, 0)
        if n:
            lines.append('  %4d %s' % (n, label))
    actionable = [1 for kind in ('items', 'objects', 'properties')
                  for v, _, _ in (p.get(kind) or [])
                  if v in (UPDATE, ADD, REMOVABLE, CONFLICT)]
    if not actionable:
        lines.append('  Nothing to do -- this world matches the starter.')

    for kind, noun in (('objects', 'Objects'), ('properties', 'Properties')):
        rows = p.get(kind) or []
        counts2: Dict[str, int] = {}
        for verdict, _, _ in rows:
            counts2[verdict] = counts2.get(verdict, 0) + 1
        actionable = {k: v for k, v in counts2.items()
                      if k in (UPDATE, ADD, REMOVABLE, CONFLICT)}
        if not actionable:
            continue
        lines += ['', '%s:' % noun]
        for verdict, label in order:
            if counts2.get(verdict):
                lines.append('  %4d %s' % (counts2[verdict], label))

    for verdict, label in ((UPDATE, 'Would update'), (ADD, 'Would add'),
                           (CONFLICT, 'Conflicts')):
        rows = [(k, why) for v, k, why in p['items'] if v == verdict]
        if not rows:
            continue
        lines += ['', '%s (verbs):' % label]
        for k, why in rows[:40]:
            lines.append('  %-34s %s' % (k, why))
        if len(rows) > 40:
            lines.append('  ... and %d more' % (len(rows) - 40))
    return lines


# ---------------------------------------------------------------------------
#   Applying
# ---------------------------------------------------------------------------

RUN_DIR = os.path.expanduser('~/.megamoo/run')


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:          # exists, owned by somebody else
        return True
    return True


def server_holding(world_db: str) -> Optional[dict]:
    """A live server with this world open, or None.

    Two writers on one SQLite file is how a world gets damaged, and the
    damage is silent -- the second writer's changes simply are not there.
    A server publishes a discovery file naming its pid; stale ones outlive
    the process that wrote them, so the pid is checked rather than the
    file's existence.
    """
    target = os.path.realpath(world_db)
    candidates = [world_db + '.api.json']
    if os.path.isdir(RUN_DIR):
        candidates += [os.path.join(RUN_DIR, f) for f in os.listdir(RUN_DIR)
                       if f.endswith('.api.json')]
    for path in candidates:
        try:
            with open(path) as fh:
                info = json.load(fh)
        except (OSError, ValueError):
            continue
        if os.path.realpath(info.get('database', '')) != target:
            continue
        pid = info.get('pid')
        if isinstance(pid, int) and _pid_alive(pid):
            return info
    return None


def _starter_verb_rows(starter_db: str) -> Dict[str, tuple]:
    con = sqlite3.connect('file:%s?mode=ro' % starter_db, uri=True)
    rows = {}
    for objnum, names, code, owner, perms, ptype, minl, hidden in con.execute(
            'select objnum,names,code,owner,perms,parent_type,min_lengths,'
            'hidden from verbs'):
        rows['%d:%s' % (objnum, json.loads(names)[0])] = (
            objnum, names, code, owner, perms, ptype, minl, hidden)
    con.close()
    return rows


def _verb_tree(world_db: str) -> Optional[str]:
    """The world's on-disk verb directory, if it has one."""
    root = os.path.dirname(os.path.abspath(world_db))
    for name in ('verbs', 'moo verbs'):
        cand = os.path.join(root, name)
        if os.path.isdir(cand):
            return cand
    return None


def apply(world_db: str, starter_db: str = STARTER_WORLD,
          chain_path: str = MANIFEST_CHAIN,
          backup: bool = True) -> dict:
    """Apply the safe half of a plan: updates and additions only.

    Conflicts and local edits are never touched -- a verb the builder
    changed is theirs, and an upgrade that overwrites it has taken their
    world away from them, which is the whole thing this must not do.
    """
    out = {'applied': [], 'skipped': [], 'backup': None, 'error': None,
           'now_at': None}

    live = server_holding(world_db)
    if live:
        out['error'] = ('a server is running on this world (pid %s, port %s). '
                        'Stop it first -- two writers on one database lose '
                        'changes silently.' % (live.get('pid'), live.get('port')))
        return out

    p = plan(world_db, starter_db, chain_path)
    if p['error']:
        out['error'] = p['error']
        return out

    todo = [(v, k) for v, k, _ in p['items'] if v in (UPDATE, ADD, REMOVABLE)]
    other = [1 for kind in ('objects', 'properties')
             for v, _, _ in p[kind] if v in (UPDATE, ADD, REMOVABLE)]
    if not todo and not other:
        return out

    if backup:
        import time
        stamp = time.strftime('%Y%m%d-%H%M%S')
        dest = '%s.pre-upgrade-%s' % (world_db, stamp)
        src = sqlite3.connect('file:%s?mode=ro' % world_db, uri=True)
        dst = sqlite3.connect(dest)
        src.backup(dst)                      # folds the WAL in as it copies
        src.close()
        dst.close()
        out['backup'] = dest

    rows = _starter_verb_rows(starter_db)
    tree = _verb_tree(world_db)
    con = sqlite3.connect(world_db)
    src = sqlite3.connect('file:%s?mode=ro' % starter_db, uri=True)

    # Objects first: a property or verb cannot be added to an object that is
    # not there yet.  Only additions -- an object already present keeps its
    # parent and name, because reparenting a live object moves everything
    # beneath it.
    for verdict, key, _why in p['objects']:
        if verdict != ADD:
            continue
        row = src.execute('select objnum,parent,noun,aliases,owner,location,'
                          'flags,created,last_move from objects where '
                          'objnum=?', (int(key),)).fetchone()
        if row is None:
            continue
        if con.execute('select 1 from objects where objnum=?',
                       (int(key),)).fetchone():
            out['skipped'].append(('#' + key, 'number already in use here'))
            continue
        con.execute('insert into objects (objnum,parent,noun,aliases,owner,'
                    'location,flags,created,last_move) values (?,?,?,?,?,?,?,?,?)',
                    row)
        out['applied'].append((ADD, '#' + key))

    # Then properties.  A value the builder never touched is the starter's
    # to correct; one they did is theirs, and _classify has already said
    # which is which.
    for verdict, key, _why in p['properties']:
        objnum, name = key.split(':', 1)
        if verdict in (ADD, UPDATE):
            row = src.execute('select value,owner,perms from properties '
                              'where objnum=? and name=?',
                              (int(objnum), name)).fetchone()
            if row is None:
                continue
            if not con.execute('select 1 from objects where objnum=?',
                               (int(objnum),)).fetchone():
                out['skipped'].append((key, 'object #%s not in this world'
                                       % objnum))
                continue
            con.execute('insert or replace into properties (objnum,name,'
                        'value,owner,perms) values (?,?,?,?,?)',
                        (int(objnum), name, row[0], row[1], row[2]))
            out['applied'].append((verdict, key))
        elif verdict == REMOVABLE:
            con.execute('delete from properties where objnum=? and name=?',
                        (int(objnum), name))
            out['applied'].append((REMOVABLE, key))
    for verdict, key in todo:
        if verdict == REMOVABLE:
            # Byte-identical to what it shipped as, and gone upstream.  Not
            # removing it is what leaves a moved verb defined twice.
            objnum, primary = key.split(':', 1)
            objnum = int(objnum)
            for names, in con.execute(
                    'select names from verbs where objnum=?', (objnum,)).fetchall():
                if json.loads(names)[0] == primary:
                    con.execute('delete from verbs where objnum=? and names=?',
                                (objnum, names))
                    break
            if tree:
                f = os.path.join(tree, str(objnum), primary + '.py')
                if os.path.exists(f):
                    os.remove(f)      # a verb file that exists is a verb
            out['applied'].append((verdict, key))
            continue
        row = rows.get(key)
        if row is None:
            out['skipped'].append((key, 'not in the starter any more'))
            continue
        objnum, names, code, owner, perms, ptype, minl, hidden = row
        if verdict == UPDATE:
            con.execute(
                'update verbs set code=?,names=?,perms=?,parent_type=?,'
                'min_lengths=?,hidden=? where objnum=? and names=?',
                (code, names, perms, ptype, minl, hidden, objnum, names))
        else:
            pos = con.execute('select coalesce(max(position),0)+1 from verbs '
                              'where objnum=?', (objnum,)).fetchone()[0]
            # The world's own owner for that object, not the starter's --
            # object numbers line up but accounts do not.
            r = con.execute('select owner from objects where objnum=?',
                            (objnum,)).fetchone()
            if r is None:
                out['skipped'].append((key, 'object #%d not in this world'
                                       % objnum))
                continue
            con.execute(
                'insert into verbs (objnum,position,names,code,owner,perms,'
                'parent_type,min_lengths,hidden) values (?,?,?,?,?,?,?,?,?)',
                (objnum, pos, names, code, r[0], perms, ptype, minl, hidden))
        if tree:
            d = os.path.join(tree, str(objnum))
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, json.loads(names)[0] + '.py'), 'w') as fh:
                fh.write(code)
        out['applied'].append((verdict, key))
    # The shipped starter is stamped into each *copy* at init, not into the
    # template, so the version it represents is the engine's own.
    from .globals import SERVER_VERSION
    starter_version = world_template_version(starter_db) or SERVER_VERSION
    if starter_version and not out['skipped']:
        con.execute("insert or replace into metadata (key,value) values "
                    "('template_version',?)", (json.dumps(starter_version),))
        out['now_at'] = starter_version
    con.commit()
    con.close()
    src.close()
    return out
