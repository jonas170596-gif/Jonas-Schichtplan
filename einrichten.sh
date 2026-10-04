#!/usr/bin/env bash
# Legt einen Starter auf den Desktop. Linux: .desktop-Datei.
# macOS: dort genuegt es, start.sh ins Dock zu ziehen.
set -e
cd "$(dirname "$0")"
ORDNER=$(pwd)
DESKTOP="${XDG_DESKTOP_DIR:-$HOME/Desktop}"
mkdir -p "$DESKTOP"
ZIEL="$DESKTOP/schichtplan.desktop"
cat > "$ZIEL" <<EOF
[Desktop Entry]
Type=Application
Name=Schichtplan Winterbach
Comment=Wocheneinsatzplan Winterbach
Exec=$ORDNER/start.sh
Path=$ORDNER
Icon=$ORDNER/schichtplan/web/bild/symbol-256.png
Terminal=true
Categories=Office;
EOF
chmod +x "$ZIEL"
echo "Starter angelegt: $ZIEL"
