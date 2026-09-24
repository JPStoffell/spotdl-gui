#!/usr/bin/env bash
# Installs SpotDL UI as a regular launchable application on this system:
#   - checks/installs Python deps (spotdl) and warns about ffmpeg/GTK
#   - installs the app icon into the user icon theme
#   - installs a .desktop launcher that shows up in the app grid / search
#
# Safe to re-run any time (e.g. after moving the project directory).

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCHER="$PROJECT_ROOT/bin/spotdl-ui"

APPLICATIONS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
DESKTOP_FILE="$APPLICATIONS_DIR/io.github.spotdl_ui.desktop"
ICON_FILE="$ICON_DIR/io.github.spotdl_ui.svg"

info()  { printf '\033[1;32m==>\033[0m %s\n' "$1"; }
warn()  { printf '\033[1;33m!!\033[0m %s\n' "$1"; }
error() { printf '\033[1;31mXX\033[0m %s\n' "$1"; }

info "Checking dependencies..."

if ! command -v python3 >/dev/null 2>&1; then
    error "python3 was not found. Install it first (it ships with Fedora Workstation by default)."
    exit 1
fi

if ! python3 -c "import gi; gi.require_version('Gtk','4.0'); gi.require_version('Adw','1'); from gi.repository import Gtk, Adw" >/dev/null 2>&1; then
    warn "GTK4 / libadwaita Python bindings are missing."
    echo "    Install them with:  sudo dnf install gtk4 libadwaita python3-gobject"
    read -r -p "Install them now with dnf (requires sudo)? [y/N] " reply
    if [[ "$reply" =~ ^[Yy]$ ]]; then
        sudo dnf install -y gtk4 libadwaita python3-gobject
    else
        error "Cannot continue without GTK4/libadwaita bindings."
        exit 1
    fi
fi

if ! command -v spotdl >/dev/null 2>&1; then
    warn "spotdl was not found on PATH."
    read -r -p "Install it now with 'pip install --user spotdl'? [Y/n] " reply
    if [[ ! "$reply" =~ ^[Nn]$ ]]; then
        python3 -m pip install --user --upgrade spotdl
    else
        warn "Skipping. Install it later with: pip install --user spotdl"
    fi
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
    warn "ffmpeg was not found. Downloads will fail to convert audio."
    echo "    Fedora (needs RPM Fusion):  sudo dnf install ffmpeg"
    echo "    ...or let spotdl fetch its own copy later:  spotdl --download-ffmpeg"
fi

info "Installing app icon..."
mkdir -p "$ICON_DIR"
cp "$PROJECT_ROOT/data/io.github.spotdl_ui.svg" "$ICON_FILE"

info "Installing desktop launcher..."
mkdir -p "$APPLICATIONS_DIR"
sed "s|__EXEC__|$LAUNCHER|" "$PROJECT_ROOT/data/io.github.spotdl_ui.desktop.in" > "$DESKTOP_FILE"
chmod +x "$LAUNCHER" "$DESKTOP_FILE"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPLICATIONS_DIR" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" >/dev/null 2>&1 || true
fi

echo
info "Done! SpotDL UI is installed."
echo "    Launch it from your application grid/search as \"SpotDL UI\","
echo "    or directly with: $LAUNCHER"
