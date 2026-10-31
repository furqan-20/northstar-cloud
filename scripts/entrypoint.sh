#!/bin/sh
set -eu
if [ "${NORTHSTAR_AUTO_INIT:-1}" = "1" ]; then
    python -m scripts.initialize
fi
exec "$@"
