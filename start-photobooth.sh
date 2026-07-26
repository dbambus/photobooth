#!/bin/bash
# Starts the photobooth, unless it is already running.
#
# Meant for a desktop launcher: starting a second instance would fail with
# "Could not claim the USB device", because the running one holds the camera.

cd "$(dirname "$0")" || exit 1

for pid in $(pgrep -f 'python -m photobooth' 2>/dev/null); do
    if [ "$(readlink "/proc/$pid/cwd" 2>/dev/null)" = "$PWD" ]; then
        echo "Photobooth is already running (PID $pid)." >&2
        exit 0
    fi
done

exec .venv/bin/python -m photobooth --run "$@"
