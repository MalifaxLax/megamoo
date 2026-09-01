#!/usr/bin/env python3
"""Record what a released starter world contained, so an existing world can
later be told apart from it.

A world is copied out of the starter by `megamoo init` and is the builder's
from that moment.  Improvements to the starter have no way back in, because
nothing can distinguish "the builder edited this" from "this is what the
starter always shipped".

A hash per item settles that, and a hash is all it takes -- the historical
*content* never has to be shipped.  With the manifest of the version a world
was born from (its `template_version`), an upgrade can classify every item:

    unchanged since birth + changed upstream  -> safe to update
    changed by the builder + changed upstream -> conflict, report it
    changed by the builder + same upstream    -> leave alone
    absent + added upstream                   -> safe to add
    unchanged + removed upstream              -> offer to remove

Usage:
    python tools/gen_world_manifest.py <world.db> <version> [-o <out.json>]
    python tools/gen_world_manifest.py --all-tags
"""
import argparse
import gzip
import hashlib
import json
import os
import sqlite3
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
STARTER = os.path.join(os.path.dirname(HERE), 'moo', 'templates', 'starter',
                       'world.db')
ENGINE = os.path.dirname(HERE)
MANIFEST_DIR = os.path.join(ENGINE, 'moo', 'templates', 'manifests')

# 16 hex chars is 64 bits.  These are change detectors, not signatures --
# an accidental collision across a few hundred items is not reachable, and
# the full digest would triple the manifest for nothing.
HASH_LEN = 16


def _h(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:HASH_LEN]


def manifest_for(db_path, version):
    """The identifying hashes of one starter world."""
    con = sqlite3.connect('file:%s?mode=ro' % db_path, uri=True)
    verbs = {}
    for objnum, names, code, perms, ptype, minl, hidden in con.execute(
            'select objnum,names,code,perms,parent_type,min_lengths,hidden '
            'from verbs'):
        primary = json.loads(names)[0]
        # Metadata is versioned separately: names, abbreviations, hidden and
        # perms drift on their own, and a world that renamed a verb has
        # edited it as surely as one that changed a line.
        meta = json.dumps([json.loads(names), perms, ptype,
                           json.loads(minl or '{}'), bool(hidden)],
                          sort_keys=True)
        verbs['%d:%s' % (objnum, primary)] = {'code': _h(code), 'meta': _h(meta)}

    # template_key is what lets an upgrade pair objects across a renumber
    # or a rename.  Worlds older than the key simply do not have one, and
    # pairing falls back to the number for them.
    tkeys = {o: json.loads(v) for o, v in con.execute(
        "select objnum,value from properties where name='template_key'")}
    objects = {}
    for objnum, parent, noun in con.execute(
            'select objnum,parent,noun from objects'):
        rec = {'parent': parent, 'noun': noun}
        if objnum in tkeys:
            rec['key'] = tkeys[objnum]
        objects[str(objnum)] = rec

    props = {}
    for objnum, name, value, perms in con.execute(
            'select objnum,name,value,perms from properties'):
        props['%d:%s' % (objnum, name)] = _h('%s\x00%s' % (value, perms))

    con.close()
    return {
        'template_version': version,
        'hash_len': HASH_LEN,
        'counts': {'verbs': len(verbs), 'objects': len(objects),
                   'properties': len(props)},
        'verbs': verbs,
        'objects': objects,
        'properties': props,
    }


def build_chain(mans):
    """Base plus per-release deltas.

    Every release is a manifest of the same few hundred items, and most
    releases change a handful of them.  Stored whole that is 798 KB for the
    back catalogue; stored as a chain it is 42 KB, which is the difference
    between shipping it and not.
    """
    chain = {'format': 1, 'hash_len': HASH_LEN,
             'base': mans[0][0], 'versions': [v for v, _ in mans],
             'full': mans[0][1], 'deltas': {}}
    for (_, prev), (cv, cur) in zip(mans, mans[1:]):
        d = {}
        for section in ('verbs', 'objects', 'properties'):
            pre, csec = prev[section], cur[section]
            changed = {k: v for k, v in csec.items() if pre.get(k) != v}
            removed = [k for k in pre if k not in csec]
            if changed:
                d.setdefault('changed', {})[section] = changed
            if removed:
                d.setdefault('removed', {})[section] = removed
        chain['deltas'][cv] = d
    return chain


def replay(chain, version):
    """Reconstruct one version's manifest from the chain."""
    if version not in chain['versions']:
        return None
    man = json.loads(json.dumps(chain['full']))          # deep copy
    if version == chain['base']:
        return man
    for v in chain['versions'][1:]:
        d = chain['deltas'].get(v, {})
        for section, items in d.get('changed', {}).items():
            man[section].update(items)
        for section, keys in d.get('removed', {}).items():
            for k in keys:
                man[section].pop(k, None)
        man['template_version'] = v
        man['counts'] = {s: len(man[s])
                         for s in ('verbs', 'objects', 'properties')}
        if v == version:
            break
    return man


def _git(*args):
    return subprocess.run(['git', '-C', ENGINE] + list(args),
                          capture_output=True)


def from_all_tags(pending=None):
    """One manifest per released tag, so worlds already in the field are
    upgradable rather than only worlds created from here on."""
    tags = _git('tag', '-l', 'v0.10.0-beta*').stdout.decode().split()
    def _n(tag):
        suffix = tag.rsplit('beta', 1)[-1]
        return int(suffix) if suffix.isdigit() else -1
    tags = [t for t in tags if _n(t) >= 0]
    tags.sort(key=_n)
    os.makedirs(MANIFEST_DIR, exist_ok=True)
    written = 0
    collected = []
    for tag in tags:
        blob = _git('show', '%s:moo/templates/starter/world.db' % tag).stdout
        if not blob:
            print('  %-22s no world.db, skipped' % tag)
            continue
        tmp = os.path.join(MANIFEST_DIR, '.tmp.db')
        with open(tmp, 'wb') as fh:
            fh.write(blob)
        version = tag.lstrip('v')
        try:
            man = manifest_for(tmp, version)
        except sqlite3.DatabaseError as exc:
            print('  %-22s unreadable (%s)' % (tag, exc))
            os.remove(tmp)
            continue
        os.remove(tmp)
        collected.append((version, man))
        c = man['counts']
        print('  %-22s %3d verbs %3d objects %4d props'
              % (version, c['verbs'], c['objects'], c['properties']))
        written += 1

    # The release being cut has no tag yet -- its world.db is the working
    # tree's.  Without this the chain always trails the release by one, and
    # a world created from the new version has no manifest to pair against.
    if pending:
        collected.append((pending, manifest_for(STARTER, pending)))
        c = collected[-1][1]['counts']
        print('  %-22s %3d verbs %3d objects %4d props  (working tree)'
              % (pending, c['verbs'], c['objects'], c['properties']))
        written += 1

    chain = build_chain(collected)
    out = os.path.join(MANIFEST_DIR, 'chain.json.gz')
    blob = json.dumps(chain, separators=(',', ':'), sort_keys=True).encode()
    with gzip.open(out, 'wb', compresslevel=9) as fh:
        fh.write(blob)

    # A chain that cannot reproduce what it was built from is worse than no
    # chain, so check every version rather than trusting the arithmetic.
    bad = [v for v, direct in collected
           if replay(chain, v)['verbs'] != direct['verbs']
           or replay(chain, v)['objects'] != direct['objects']
           or replay(chain, v)['properties'] != direct['properties']]
    print()
    print('  chain: %s  (%.1f KB)' % (out, os.path.getsize(out) / 1024))
    print('  replay check: %d/%d versions reproduce exactly%s'
          % (len(collected) - len(bad), len(collected),
             '' if not bad else '  MISMATCH: %s' % bad))
    return written


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('world', nargs='?')
    ap.add_argument('version', nargs='?')
    ap.add_argument('-o', '--output')
    ap.add_argument('--all-tags', action='store_true')
    ap.add_argument('--pending', metavar='VERSION',
                    help='append the working tree\'s starter as VERSION, for '
                         'the release being cut before its tag exists')
    a = ap.parse_args()

    if a.all_tags:
        n = from_all_tags(pending=a.pending)
        return 0

    if not a.world or not a.version:
        ap.error('need <world.db> and <version>, or --all-tags')
    man = manifest_for(a.world, a.version)
    out = a.output or os.path.join(MANIFEST_DIR, '%s.json' % a.version)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w') as fh:
        json.dump(man, fh, separators=(',', ':'), sort_keys=True)
    print('wrote %s (%d bytes)' % (out, os.path.getsize(out)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
