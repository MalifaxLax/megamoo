#!/bin/sh
# Kept as an alias.  Everything this script used to do now lives in the
# packaged command as `megamoo --dev`: the shared API token, the
# discovery file that lets tooling find a running world, verb
# autoreload, and picking the obvious database.
#
# The two things it did that had to go: it cd'd into the engine
# checkout, so it could only ever run a database living inside the
# engine, and it hardcoded one machine's Python interpreter.
exec megamoo --dev "$@"
