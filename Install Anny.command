#!/bin/bash
set -euo pipefail

APP_NAME="Anny.app"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_SRC="$SRC_DIR/$APP_NAME"
DEST_DIR="/Applications"
DEST="$DEST_DIR/$APP_NAME"

if [ ! -d "$APP_SRC" ]; then
  echo "Cannot find $APP_NAME next to this installer. Please run it directly from the mounted DMG." >&2
  exit 1
fi

echo "→ Copying $APP_NAME to $DEST_DIR"
rm -rf "$DEST"
if command -v ditto >/dev/null 2>&1; then
  ditto "$APP_SRC" "$DEST"
else
  cp -R "$APP_SRC" "$DEST"
fi

if [ ! -d "$DEST" ]; then
  echo "Copy failed; please re-run the installer." >&2
  exit 1
fi

GS_INIT="$DEST/Contents/Resources/ghostscript/share/ghostscript/Resource/Init/gs_init.ps"
if [ ! -f "$GS_INIT" ]; then
  echo "Installation looks incomplete (missing $GS_INIT). Delete $DEST and re-run this installer." >&2
  exit 1
fi

echo "→ Removing quarantine flag"
xattr -dr com.apple.quarantine "$DEST" || true

echo "→ Verifying bundled Ghostscript"
if ! "$DEST/Contents/Resources/ghostscript/bin/gs" -q -dBATCH -c quit; then
  echo "Ghostscript self-test failed. Delete $DEST and rerun this installer." >&2
  exit 1
fi

echo "✓ Installed. Launching Anny..."
open "$DEST"
