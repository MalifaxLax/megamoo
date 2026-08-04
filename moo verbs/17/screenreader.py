"""Toggle screen reader mode. Usage: screenreader"""

settings = player.settings or {}
current = settings.get('screenreader', False)
settings['screenreader'] = not current
player.settings = settings
if settings['screenreader']:
    player.msg("Screen reader mode ON. Color codes stripped from all output.")
else:
    player.msg("Screen reader mode OFF. Color codes restored.")
