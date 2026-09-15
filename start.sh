#!/usr/bin/env bash
# Start the store bot on this machine.
# Configuration is read from .env — copy .env.example if you have not yet.
set -u
cd "$(dirname "$0")"

if [ ! -f .env ]; then
    echo "No .env found."
    echo "Copy .env.example to .env and fill in BOT_TOKEN and ADMIN_IDS."
    exit 1
fi

PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then
    echo "Python not found on PATH."
    exit 1
fi

echo "Installing dependencies..."
"$PY" -m pip install --quiet --disable-pip-version-check -r requirements.txt

echo
echo "Starting the bot. Press Ctrl+C to stop."
echo

# Restart on a crash, but let Ctrl+C (130) and a clean exit through.
while true; do
    "$PY" bot.py
    code=$?
    echo
    echo "Bot stopped with exit code $code."
    if [ "$code" -eq 0 ] || [ "$code" -eq 130 ]; then
        break
    fi
    echo "Restarting in 5 seconds... press Ctrl+C to stop."
    sleep 5
done
