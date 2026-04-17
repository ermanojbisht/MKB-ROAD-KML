#!/usr/bin/env bash
# install-linux.sh — Install MKB-ROAD-KML on Ubuntu 22.04+
#
# Usage (after building with PyInstaller):
#   bash install-linux.sh
#
# What it does:
#   1. Copies dist/mkb-road-kml/ to /opt/mkb-road-kml/
#   2. Creates a symlink in /usr/local/bin/mkb-road-kml
#   3. Installs the .desktop entry to ~/.local/share/applications/
#   4. Refreshes the application menu

set -e

DIST_DIR="$(cd "$(dirname "$0")/dist/mkb-road-kml" && pwd)"
INSTALL_DIR="/opt/mkb-road-kml"
DESKTOP_FILE="$(dirname "$0")/mkb-road-kml.desktop"
APP_DIR="$HOME/.local/share/applications"

if [ ! -d "$DIST_DIR" ]; then
    echo "ERROR: dist/mkb-road-kml/ not found."
    echo "Build it first:  pyinstaller mkb-road-kml-linux.spec"
    exit 1
fi

echo "Installing to $INSTALL_DIR ..."
sudo mkdir -p "$INSTALL_DIR"
sudo cp -r "$DIST_DIR/." "$INSTALL_DIR/"
sudo chmod +x "$INSTALL_DIR/mkb-road-kml"

echo "Creating symlink /usr/local/bin/mkb-road-kml ..."
sudo ln -sf "$INSTALL_DIR/mkb-road-kml" /usr/local/bin/mkb-road-kml

echo "Installing .desktop entry ..."
mkdir -p "$APP_DIR"
cp "$DESKTOP_FILE" "$APP_DIR/mkb-road-kml.desktop"
chmod +x "$APP_DIR/mkb-road-kml.desktop"

# Refresh menu
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "$APP_DIR"
fi
if command -v xdg-desktop-menu &>/dev/null; then
    xdg-desktop-menu forceupdate
fi

echo ""
echo "Done!  Launch with:"
echo "  mkb-road-kml          (from terminal)"
echo "  Search 'MKB-ROAD-KML' in your app launcher"
