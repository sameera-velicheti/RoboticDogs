#!/bin/bash
# Installs the Agentic Paw Patrol desktop icon on this computer.
# Run once on the Dell:  bash install_desktop_icon.sh

set -e

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
LAUNCHER="$APP_DIR/start_pawpatrol.sh"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
APPS_DIR="$HOME/.local/share/applications"
ENTRY_NAME="PawPatrol.desktop"

if [ ! -f "$LAUNCHER" ]; then
    echo "ERROR: Could not find $LAUNCHER"
    exit 1
fi

chmod +x "$LAUNCHER"
echo "Made start_pawpatrol.sh executable"

mkdir -p "$DESKTOP_DIR" "$APPS_DIR"

TMP_ENTRY="$(mktemp)"
cat > "$TMP_ENTRY" <<EOF
[Desktop Entry]
Type=Application
Name=Agentic Paw Patrol
Comment=Start the robotic dogs inspection application
Exec="$LAUNCHER"
Path=$APP_DIR
Icon=$APP_DIR/static/app_icon.svg
Terminal=false
Categories=Utility;
EOF

for target in "$DESKTOP_DIR/$ENTRY_NAME" "$APPS_DIR/$ENTRY_NAME"; do
    cp "$TMP_ENTRY" "$target"
    chmod +x "$target"
    echo "Installed $target"
done
rm -f "$TMP_ENTRY"

# Mark the desktop icon as trusted so Ubuntu lets it launch
if gio set "$DESKTOP_DIR/$ENTRY_NAME" metadata::trusted true 2>/dev/null; then
    echo "Marked desktop icon as trusted"
else
    echo "Could not mark the icon as trusted automatically."
    echo "Right-click the desktop icon and choose 'Allow Launching'."
fi

update-desktop-database "$APPS_DIR" 2>/dev/null || true

echo ""
echo "Done. Project folder: $APP_DIR"
echo "Double-click 'Agentic Paw Patrol' on the desktop to start the app."