#!/usr/bin/env bash
# Removes the desktop launcher and icon installed by install.sh.
# Leaves spotdl/ffmpeg and the project files themselves untouched.

set -euo pipefail

APPLICATIONS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
DESKTOP_FILE="$APPLICATIONS_DIR/io.github.spotdl_ui.desktop"
ICON_FILE="$ICON_DIR/io.github.spotdl_ui.svg"

rm -f "$DESKTOP_FILE" "$ICON_FILE"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPLICATIONS_DIR" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" >/dev/null 2>&1 || true
fi

echo "Removed the SpotDL UI launcher and icon."
