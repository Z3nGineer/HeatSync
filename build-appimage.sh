#!/usr/bin/env bash
# build-appimage.sh — rebuild HeatSync.AppImage from current source
# Usage: bash build-appimage.sh
set -e
cd "$(dirname "${BASH_SOURCE[0]}")"

VENV=".venv/bin"
APPDIR="AppDir"
ICON_TMP="/tmp/heatsync256.png"

echo "=== HeatSync AppImage build ==="

# ── 0. Kill running instance so the binary can be overwritten ─────────────────
pkill -f "HeatSync.py\|HeatSync.AppImage" 2>/dev/null || true
sleep 0.3

# ── 1. Resize icon to 256×256 (linuxdeploy rejects non-standard sizes) ────────
"$VENV/python" - <<'EOF'
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPixmap
import sys
app = QApplication(sys.argv)
QPixmap("AppDir/heatsync.png").scaled(256, 256).save("/tmp/heatsync256.png")
EOF

# ── 2. PyInstaller → single self-contained binary ─────────────────────────────
echo "[1/2] PyInstaller..."
"$VENV/pyinstaller" HeatSync.spec \
    --distpath "$APPDIR/usr/bin" \
    --workpath /tmp/heatsync-build \
    --noconfirm -y 2>&1 \
    | grep -E "^(INFO:.*EXE|WARNING:.*Missing|ERROR)" || true
echo "      Binary ready: $APPDIR/usr/bin/HeatSync"

# ── 3. linuxdeploy → AppDir + squashfs + runtime = AppImage ──────────────────
echo "[2/2] linuxdeploy → AppImage..."
chmod +x linuxdeploy-x86_64.AppImage

ARCH=x86_64 ./linuxdeploy-x86_64.AppImage \
    --appdir "$APPDIR" \
    --executable "$APPDIR/usr/bin/HeatSync" \
    --desktop-file "$APPDIR/heatsync.desktop" \
    --icon-file "$ICON_TMP" \
    --output appimage 2>&1 \
    | grep -E "^\[(appimage|linuxdeploy)\]|ERROR|Success" || true

# linuxdeploy names output HeatSync-x86_64.AppImage — normalize it
[ -f HeatSync-x86_64.AppImage ] && mv -f HeatSync-x86_64.AppImage HeatSync.AppImage

chmod +x HeatSync.AppImage
echo ""
echo "Done → HeatSync.AppImage ($(du -sh HeatSync.AppImage | cut -f1))"
