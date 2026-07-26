"""
Displays a reference table of pronoun substitution tags available for
use in MOO messages. Shows all gender variants and their corresponding
%ps, %po, %pp, %pa, %pr substitution codes.

Usage: +pron

Auth: gm2+ (auth_level 2)

Note: Also shows %S/%D/%I substitution tags for subject/dobj/iobj names.
Uppercase 'P' variants capitalize the output.
"""

if auth_level(pobj) < 2:
    pobj.msg("Do what?")
    return

pmap = globals.GENDER_PRONOUN_MAP

pobj.msg("")
pobj.msg("%<245>Pronoun substitution tags for msg:%n")
pobj.msg("  %%ps / %%Ps = subject    (he, she, it, they)")
pobj.msg("  %%po / %%Po = object     (him, her, it, them)")
pobj.msg("  %%pp / %%Pp = possessive (his, her, its, their)")
pobj.msg("  %%pa / %%Pa = absolute   (his, hers, its, theirs)")
pobj.msg("  %%pr / %%Pr = reflexive  (himself, herself, itself, themself)")
pobj.msg("  Uppercase P = capitalize output.")
pobj.msg("")
pobj.msg("  Gender        %%ps    %%po    %%pp    %%pa      %%pr")
for gender, pronouns in pmap.items():
    ps = pronouns['ps'].ljust(6)
    po = pronouns['po'].ljust(6)
    pp = pronouns['pp'].ljust(6)
    pa = pronouns['pa'].ljust(8)
    pr = pronouns['pr']
    pobj.msg(f"  {gender.ljust(13)} {ps} {po} {pp} {pa} {pr}")

pobj.msg("")
pobj.msg("Other tags: %%S/%%s = sub name, %%D/%%d = dobj name, %%I/%%i = iobj name")
