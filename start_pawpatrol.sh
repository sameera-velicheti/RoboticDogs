#!/bin/bash
# Paw Patrol launcher: starts the app if it isn't running, then opens the pairing screen.

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
STATUS_URL="http://localhost:5000/api/status"
OPEN_URL="http://localhost:5000/new"
LOG="$APP_DIR/pawpatrol.log"

# Find the virtual environment: venv, then .venv, then ~/pawpatrol-venv
VENV=""
for candidate in "$APP_DIR/venv" "$APP_DIR/.venv" "$HOME/pawpatrol-venv"; do
    if [ -f "$candidate/bin/activate" ]; then
        VENV="$candidate"
        break
    fi
done

if ! curl -s -o /dev/null "$STATUS_URL"; then
    if [ -z "$VENV" ]; then
        echo "No virtual environment found. Looked in:" > "$LOG"
        echo "  $APP_DIR/venv" >> "$LOG"
        echo "  $APP_DIR/.venv" >> "$LOG"
        echo "  $HOME/pawpatrol-venv" >> "$LOG"
        notify-send "Paw Patrol" "No virtual environment found. See $LOG" 2>/dev/null
        xdg-open "$LOG" > /dev/null 2>&1 &
        exit 1
    fi

    cd "$APP_DIR"
    source "$VENV/bin/activate"

    # Flask dev server for now; switch to serve.py once Waitress is tested
    nohup python3 app.py > "$LOG" 2>&1 &

    # wait up to 30 seconds for the app to answer
    for i in $(seq 1 30); do
        curl -s -o /dev/null "$STATUS_URL" && break
        sleep 1
    done
fi

if curl -s -o /dev/null "$STATUS_URL"; then
    xdg-open "$OPEN_URL" > /dev/null 2>&1 &
else
    notify-send "Paw Patrol" "The app didn't start. See $LOG" 2>/dev/null
    xdg-open "$LOG" > /dev/null 2>&1 &
fi