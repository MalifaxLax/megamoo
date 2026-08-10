"""
_title verb on #1 (RootObject).

Rebuilds an object's display name from its name_mod_list components.
The name_mod_list is a 5-element list: [article, adj1, adj2, adj3, trailer].
Combines these with the object's noun to form the full display name.

Called programmatically after modifying name_mod_list components.

Handles a/an article correction based on the first letter of the next
word (vowel -> "an", consonant -> "a"). Sets this.name.

It used to set a this.cname alongside it -- the same string with its
first letter raised. Nothing stores that now: emit substitution raises
it for &S/&D/&I, and a verb that needs it says su.capitalise(x.name).
A second copy of a name only drifts from the first.

Hidden:  yes
"""

if this.name_mod_list:
    nml = list(this.name_mod_list)
    while len(nml) < 5:
        nml.append('')
else:
    nml = ['', '', '', '', '']
article = (nml[0] or '').strip()
adjs = [a.strip() for a in nml[1:4] if a and a.strip()]
trailer = (nml[4] or '').strip()
noun = (this.noun or '').strip()
if article.lower() in ('a', 'an'):
    first_word = adjs[0] if adjs else noun
    if first_word and first_word[0].lower() in 'aeiou':
        article = 'an' if article[0].islower() else 'An'
    else:
        article = 'a' if article[0].islower() else 'A'
    nml[0] = article
parts = [p for p in [article] + adjs + [noun] if p]
name = ' '.join(parts)
if trailer:
    name = f'{name} {trailer}'
this.name = name
this.name_mod_list = nml
