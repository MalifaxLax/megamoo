#!/usr/bin/env python3
"""
Inject verbs into sf.sqlite from mm.sqlite + git history.

sf.sqlite has the sf.db object structure (renumbered) but almost no verbs.
This script:
  1. Creates Base_Character (#3) from mm.sqlite (parent for OChar/IChar)
  2. Converts #53/#54 from BlankArmor to effects_utils/help_utils
  3. Copies engine verbs from mm.sqlite for all matching objects
  4. Adds game-specific verbs from the initial commit (combat, training, etc.)
  5. Reparents OCharacter/ICharacter to Base_Character

Usage:
    python inject_verbs.py
"""

import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

MM_SQLITE = Path(__file__).parent.parent / 'megadev' / 'mm.sqlite'
SF_SQLITE = Path(__file__).parent / 'sf.sqlite'
MEGADEV = Path(__file__).parent.parent / 'megadev'

# Objects in mm.sqlite that match sf.sqlite objects (same role, same number)
MATCHING_OBJECTS = [
    1,   # Root_Object
    # 3 is created fresh below
    4,   # OCharacter
    5,   # ICharacter
    10,  # BaseObject
    11,  # object
    15,  # BaseRoom
    16,  # OCRoom
    17,  # ICRoom
    20,  # BaseExit
    21,  # DirectionalExit
    22,  # GoExit
    23,  # ClosableGoExit
    24,  # ClimbableExit
    25,  # JumpableExit
    26,  # BaseContainer
    27,  # ChestContainer
    28,  # CupContainer
    30,  # BaseFurniture
    35,  # BaseWearable
    90,  # BaseEdible
    91,  # BaseDrinkable
]

# Objects where mm.sqlite #N is different from sf.sqlite #N — skip verb copy
SKIP_OBJECTS = {
    7,   # mm=arch (chargen), sf=TrashBin
    50,  # mm=TheVoid, sf=BaseArmor
    51,  # mm=gate, sf=BlankArmor
    52,  # mm=Malifax, sf=BlankArmor
}

# Objects to REPLACE in sf.sqlite with mm.sqlite versions (different role)
REPLACE_OBJECTS = {
    53,  # sf=BlankArmor → mm=effects_utils
    54,  # sf=BlankArmor → mm=help_utils
}


def get_all_verbs(conn, objnum):
    """Get all verbs for an object."""
    return conn.execute(
        """SELECT position, names, code, owner, perms, parent_type,
                  min_lengths, hidden, auth
           FROM verbs WHERE objnum = ? ORDER BY position""",
        (objnum,)
    ).fetchall()


def get_all_properties(conn, objnum):
    """Get all properties for an object."""
    return conn.execute(
        """SELECT name, value, owner, perms
           FROM properties WHERE objnum = ? ORDER BY name""",
        (objnum,)
    ).fetchall()


def insert_verbs(conn, objnum, verbs, start_position=0):
    """Insert verbs into sf.sqlite, renumbering positions from start_position."""
    for i, row in enumerate(verbs):
        conn.execute(
            """INSERT INTO verbs (objnum, position, names, code, owner, perms,
                                  parent_type, min_lengths, hidden, auth)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (objnum, start_position + i, row[1], row[2], row[3], row[4],
             row[5], row[6], row[7], row[8])
        )
    return len(verbs)


def get_git_object(objnum):
    """Extract an object from the initial git commit's megamoo.db."""
    filename = f'megamoo.db/objects/{objnum:06d}.json'
    try:
        result = subprocess.run(
            ['git', 'show', f'5b4ef70:{filename}'],
            capture_output=True, text=True, cwd=str(MEGADEV)
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception:
        pass
    return None


def find_game_verbs(mm_conn, objnum):
    """
    Find verbs that existed in the initial commit but were removed from mm.sqlite.
    Returns list of verb dicts from the initial commit that aren't in mm.sqlite.
    """
    git_obj = get_git_object(objnum)
    if not git_obj or not git_obj.get('verbs'):
        return []

    # Get current mm.sqlite verb names
    mm_verbs = get_all_verbs(mm_conn, objnum)
    mm_names = set()
    for row in mm_verbs:
        for name in json.loads(row[1]):
            mm_names.add(name)

    # Find verbs in initial commit that are gone from mm.sqlite
    missing = []
    for verb in git_obj['verbs']:
        verb_names = set(verb.get('names', []))
        if not verb_names & mm_names:
            missing.append(verb)

    return missing


def main():
    if not MM_SQLITE.exists():
        print(f"ERROR: mm.sqlite not found at {MM_SQLITE}")
        sys.exit(1)
    if not SF_SQLITE.exists():
        print(f"ERROR: sf.sqlite not found at {SF_SQLITE}")
        sys.exit(1)

    mm_conn = sqlite3.connect(str(MM_SQLITE))
    sf_conn = sqlite3.connect(str(SF_SQLITE))

    total_verbs_added = 0

    # ------------------------------------------------------------------
    # Step 1: Create Base_Character (#3)
    # ------------------------------------------------------------------
    print("\n=== Step 1: Create Base_Character (#3) ===")

    # Get Base_Character from mm.sqlite
    mm_obj = mm_conn.execute(
        "SELECT objnum, parent, noun, aliases, owner, location, flags, created, last_move "
        "FROM objects WHERE objnum = 3"
    ).fetchone()

    if mm_obj:
        # Remove from recycled_objects
        sf_conn.execute("DELETE FROM recycled_objects WHERE objnum = 3")

        # Insert object
        sf_conn.execute(
            """INSERT OR REPLACE INTO objects
               (objnum, parent, noun, aliases, owner, location, flags, created, last_move)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (3, 10, 'Base_Character', mm_obj[3], 0, 0, mm_obj[6],
             mm_obj[7], mm_obj[8])
        )

        # Copy properties from mm.sqlite
        mm_props = get_all_properties(mm_conn, 3)
        for prop in mm_props:
            sf_conn.execute(
                """INSERT INTO properties (objnum, name, value, owner, perms)
                   VALUES (?, ?, ?, ?, ?)""",
                (3, prop[0], prop[1], prop[2], prop[3])
            )
        print(f"  Created Base_Character (#3) with {len(mm_props)} properties")

        # Copy verbs from mm.sqlite
        mm_verbs = get_all_verbs(mm_conn, 3)
        count = insert_verbs(sf_conn, 3, mm_verbs)
        total_verbs_added += count
        print(f"  Added {count} verbs to Base_Character (#3)")

        # Check for game-specific verbs from initial commit
        game_verbs = find_game_verbs(mm_conn, 3)
        if game_verbs:
            next_pos = count
            for verb in game_verbs:
                sf_conn.execute(
                    """INSERT INTO verbs (objnum, position, names, code, owner, perms,
                                          parent_type, min_lengths, hidden, auth)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (3, next_pos, json.dumps(verb['names']), verb.get('code', ''),
                     0, verb.get('perms', 'rx'),
                     verb.get('parent_type', 'moo.verb_types.MasterVerb'),
                     json.dumps(verb.get('min_lengths', {})),
                     int(verb.get('hidden', 0)), verb.get('auth', 0))
                )
                next_pos += 1
                total_verbs_added += 1
            print(f"  Added {len(game_verbs)} game-specific verbs from git history")
    else:
        print("  WARNING: Base_Character not found in mm.sqlite")

    # ------------------------------------------------------------------
    # Step 2: Replace #53/#54 with effects_utils/help_utils
    # ------------------------------------------------------------------
    print("\n=== Step 2: Replace #53/#54 with effects_utils/help_utils ===")

    for objnum in sorted(REPLACE_OBJECTS):
        mm_obj = mm_conn.execute(
            "SELECT objnum, parent, noun, aliases, owner, location, flags, created, last_move "
            "FROM objects WHERE objnum = ?", (objnum,)
        ).fetchone()

        if mm_obj:
            # Update the object metadata
            sf_conn.execute(
                """UPDATE objects SET parent=?, noun=?, aliases=?, owner=?,
                   location=?, flags=? WHERE objnum=?""",
                (1, mm_obj[2], mm_obj[3], 0, 0, mm_obj[6], objnum)
            )

            # Remove old properties and add mm ones
            sf_conn.execute("DELETE FROM properties WHERE objnum = ?", (objnum,))
            mm_props = get_all_properties(mm_conn, objnum)
            for prop in mm_props:
                sf_conn.execute(
                    """INSERT INTO properties (objnum, name, value, owner, perms)
                       VALUES (?, ?, ?, ?, ?)""",
                    (objnum, prop[0], prop[1], prop[2], prop[3])
                )

            # Add verbs
            mm_verbs = get_all_verbs(mm_conn, objnum)
            count = insert_verbs(sf_conn, objnum, mm_verbs)
            total_verbs_added += count
            print(f"  #{objnum} ({mm_obj[2]}): replaced with {len(mm_props)} props, {count} verbs")
        else:
            print(f"  WARNING: #{objnum} not found in mm.sqlite")

    # ------------------------------------------------------------------
    # Step 3: Copy engine verbs for matching objects
    # ------------------------------------------------------------------
    print("\n=== Step 3: Copy engine verbs from mm.sqlite ===")

    for objnum in sorted(MATCHING_OBJECTS):
        # Check object exists in sf.sqlite
        sf_exists = sf_conn.execute(
            "SELECT objnum FROM objects WHERE objnum = ?", (objnum,)
        ).fetchone()
        if not sf_exists:
            print(f"  #{objnum}: SKIP (not in sf.sqlite)")
            continue

        # Remove any existing verbs (start clean)
        sf_conn.execute("DELETE FROM verbs WHERE objnum = ?", (objnum,))

        # Copy verbs from mm.sqlite
        mm_verbs = get_all_verbs(mm_conn, objnum)
        if not mm_verbs:
            continue

        count = insert_verbs(sf_conn, objnum, mm_verbs)
        total_verbs_added += count

        mm_noun = mm_conn.execute(
            "SELECT noun FROM objects WHERE objnum = ?", (objnum,)
        ).fetchone()
        noun = mm_noun[0] if mm_noun else '?'
        print(f"  #{objnum} ({noun}): {count} engine verbs")

    # ------------------------------------------------------------------
    # Step 4: Add game-specific verbs from git history
    # ------------------------------------------------------------------
    print("\n=== Step 4: Add game-specific verbs from git history ===")

    for objnum in sorted(MATCHING_OBJECTS):
        sf_exists = sf_conn.execute(
            "SELECT objnum FROM objects WHERE objnum = ?", (objnum,)
        ).fetchone()
        if not sf_exists:
            continue

        game_verbs = find_game_verbs(mm_conn, objnum)
        if not game_verbs:
            continue

        # Get current max position
        max_pos = sf_conn.execute(
            "SELECT MAX(position) FROM verbs WHERE objnum = ?", (objnum,)
        ).fetchone()[0]
        next_pos = (max_pos + 1) if max_pos is not None else 0

        for verb in game_verbs:
            sf_conn.execute(
                """INSERT INTO verbs (objnum, position, names, code, owner, perms,
                                      parent_type, min_lengths, hidden, auth)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (objnum, next_pos, json.dumps(verb['names']), verb.get('code', ''),
                 0, verb.get('perms', 'rx'),
                 verb.get('parent_type', 'moo.verb_types.MasterVerb'),
                 json.dumps(verb.get('min_lengths', {})),
                 int(verb.get('hidden', 0)), verb.get('auth', 0))
            )
            next_pos += 1
            total_verbs_added += 1

        sf_noun = sf_conn.execute(
            "SELECT noun FROM objects WHERE objnum = ?", (objnum,)
        ).fetchone()[0]
        print(f"  #{objnum} ({sf_noun}): +{len(game_verbs)} game verbs: "
              f"{[v['names'] for v in game_verbs]}")

    # ------------------------------------------------------------------
    # Step 4b: Add train/exp verbs to ICRoom (#17) from verb files
    # ------------------------------------------------------------------
    print("\n=== Step 4b: Add train/exp verbs from verb files ===")

    verb_files = {
        17: [
            ('train.py', ['train']),
            ('exp.py', ['exp']),
        ],
    }

    for objnum, files in verb_files.items():
        sf_exists = sf_conn.execute(
            "SELECT objnum FROM objects WHERE objnum = ?", (objnum,)
        ).fetchone()
        if not sf_exists:
            continue

        max_pos = sf_conn.execute(
            "SELECT MAX(position) FROM verbs WHERE objnum = ?", (objnum,)
        ).fetchone()[0]
        next_pos = (max_pos + 1) if max_pos is not None else 0

        for filename, names in files:
            filepath = Path(__file__).parent / 'moo verbs' / str(objnum) / filename
            if not filepath.exists():
                print(f"  WARNING: {filepath} not found")
                continue

            # Check if verb already exists
            existing = sf_conn.execute(
                "SELECT names FROM verbs WHERE objnum = ?", (objnum,)
            ).fetchall()
            existing_names = set()
            for row in existing:
                for n in json.loads(row[0]):
                    existing_names.add(n)

            if set(names) & existing_names:
                print(f"  #{objnum}: {names} already exists, skipping")
                continue

            code = filepath.read_text()
            sf_conn.execute(
                """INSERT INTO verbs (objnum, position, names, code, owner, perms,
                                      parent_type, min_lengths, hidden, auth)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (objnum, next_pos, json.dumps(names), code, 0, 'rx',
                 'moo.verb_types.MasterVerb', '{}', 0, 0)
            )
            next_pos += 1
            total_verbs_added += 1
            print(f"  #{objnum}: added {names} from {filename}")

    # ------------------------------------------------------------------
    # Step 5: Reparent OCharacter/ICharacter to Base_Character
    # ------------------------------------------------------------------
    print("\n=== Step 5: Reparent objects ===")

    reparents = {
        4: 3,   # OCharacter → Base_Character
        5: 3,   # ICharacter → Base_Character
    }

    for objnum, new_parent in reparents.items():
        old_parent = sf_conn.execute(
            "SELECT parent FROM objects WHERE objnum = ?", (objnum,)
        ).fetchone()
        if old_parent and old_parent[0] != new_parent:
            sf_conn.execute(
                "UPDATE objects SET parent = ? WHERE objnum = ?",
                (new_parent, objnum)
            )
            noun = sf_conn.execute(
                "SELECT noun FROM objects WHERE objnum = ?", (objnum,)
            ).fetchone()[0]
            print(f"  #{objnum} ({noun}): parent {old_parent[0]} → {new_parent}")

    # ------------------------------------------------------------------
    # Step 6: Add missing properties from mm.sqlite
    # ------------------------------------------------------------------
    print("\n=== Step 6: Add missing properties from mm.sqlite ===")

    # For ICharacter and OCharacter, merge properties from mm.sqlite that
    # don't exist in sf.sqlite
    PROP_MERGE_OBJECTS = [4, 5, 10, 90, 91]

    for objnum in PROP_MERGE_OBJECTS:
        sf_props = set(row[0] for row in sf_conn.execute(
            "SELECT name FROM properties WHERE objnum = ?", (objnum,)
        ).fetchall())

        mm_props = get_all_properties(mm_conn, objnum)
        added = 0
        for prop in mm_props:
            if prop[0] not in sf_props:
                sf_conn.execute(
                    """INSERT INTO properties (objnum, name, value, owner, perms)
                       VALUES (?, ?, ?, ?, ?)""",
                    (objnum, prop[0], prop[1], prop[2], prop[3])
                )
                added += 1

        if added > 0:
            noun = sf_conn.execute(
                "SELECT noun FROM objects WHERE objnum = ?", (objnum,)
            ).fetchone()[0]
            print(f"  #{objnum} ({noun}): +{added} properties from mm.sqlite")

    # ------------------------------------------------------------------
    # Done
    # ------------------------------------------------------------------
    sf_conn.commit()

    # Summary
    print(f"\n{'='*60}")
    print(f"DONE: {total_verbs_added} verbs added total")

    print("\nVerb counts per object:")
    rows = sf_conn.execute(
        "SELECT o.objnum, o.noun, COUNT(v.position) "
        "FROM objects o LEFT JOIN verbs v ON o.objnum = v.objnum "
        "GROUP BY o.objnum HAVING COUNT(v.position) > 0 "
        "ORDER BY o.objnum"
    ).fetchall()
    for objnum, noun, count in rows:
        print(f"  #{objnum:3d} ({noun}): {count} verbs")

    total_objs = sf_conn.execute("SELECT COUNT(*) FROM objects").fetchone()[0]
    total_verbs = sf_conn.execute("SELECT COUNT(*) FROM verbs").fetchone()[0]
    total_props = sf_conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0]
    print(f"\nTotals: {total_objs} objects, {total_verbs} verbs, {total_props} properties")

    mm_conn.close()
    sf_conn.close()


if __name__ == '__main__':
    main()
