"""
View help topics or get help on a specific command.

Usage: help [topic]
       help #<object>            - Show help text for an object (gm3+)
       help #<object>.<verb>     - Show help for a verb on an object (gm3+)

Examples:
    help            - List all available help topics
    help look       - Get help on the look command
    help combat     - Read about a help topic
    help #42        - Show help text for object #42
    help #42.go     - Show help for the go verb on #42
"""

hu = sysobj('help_utils')
plevel = auth_level(pobj)

def _show(found, missing="There's no help for that."):
    """Print a [heading, text] pair, or say there is none."""
    if not found:
        pobj.msg(missing)
        return
    pobj.msg('\n&<245>%s&n' % found[0])
    pobj.msg(found[1])

if not args:
    topics = hu.topics(plevel)
    commands = hu.command_topics(pobj, plevel, topics)

    pobj.msg("")
    if topics:
        pobj.msg("&<245>Help Topics&n")
        pobj.msg(', '.join(topics))
    if commands:
        if topics:
            pobj.msg("")
        pobj.msg("&<245>Command Help&n")
        pobj.msg(', '.join(commands))
    if not topics and not commands:
        pobj.msg("No help topics available.")
    return

topic = args.strip()

if topic.startswith('#'):
    if plevel < 3:
        pobj.msg("There's no help for that.")
        return
    obj_part, _, verb_part = topic[1:].partition('.')
    if not obj_part.isdigit():
        pobj.msg("There's no help for that.")
        return
    obj = db.get_object(int(obj_part))
    if not obj:
        pobj.msg("There's no help for that.")
        return
    if '.' in topic[1:]:
        found = hu.verb_help(obj, verb_part, plevel)
        if found:
            found = ['#%s.%s' % (obj_part, found[0]), found[1]]
        _show(found, "No help available for '%s'." % verb_part
              if verb_part else "There's no help for that.")
        return
    _show(hu.object_help(obj))
    return

found = hu.text_for(topic, plevel)
if not found:
    for obj in [pobj, pobj.location] + list(pobj.location.contents):
        if not obj:
            continue
        found = hu.verb_help(obj, topic, plevel, True)
        if found:
            break

_show(found)
