#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="ClipNest"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-$ROOT_DIR/.venv-macos}"
DIST_DIR="$ROOT_DIR/dist_macos"
BUILD_DIR="$ROOT_DIR/build_macos"
RELEASE_DIR="$ROOT_DIR/release/macos"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python not found: $PYTHON_BIN"
  exit 1
fi

if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r "$ROOT_DIR/requirements.txt" pyinstaller pillow

icon_args=()
if [[ -f "$ROOT_DIR/assets/clipnest.icns" ]]; then
  icon_args+=(--icon "$ROOT_DIR/assets/clipnest.icns")
elif [[ -f "$ROOT_DIR/assets/clipnest.png" ]]; then
  echo "Tip: Add assets/clipnest.icns for best macOS dock icon quality."
fi

data_args=()
if [[ -f "$ROOT_DIR/assets/clipnest.ico" ]]; then
  data_args+=(--add-data "$ROOT_DIR/assets/clipnest.ico:assets")
fi
if [[ -f "$ROOT_DIR/assets/clipnest.png" ]]; then
  data_args+=(--add-data "$ROOT_DIR/assets/clipnest.png:assets")
fi

rm -rf "$BUILD_DIR" "$DIST_DIR/$APP_NAME.app"
mkdir -p "$RELEASE_DIR"

python -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "$APP_NAME" \
  --distpath "$DIST_DIR" \
  --workpath "$BUILD_DIR" \
  --specpath "$ROOT_DIR" \
  "${icon_args[@]}" \
  "${data_args[@]}" \
  "$ROOT_DIR/main.py"

if [[ ! -d "$DIST_DIR/$APP_NAME.app" ]]; then
  echo "Build failed: $DIST_DIR/$APP_NAME.app not found"
  exit 1
fi

rm -rf "$RELEASE_DIR/$APP_NAME.app"
cp -R "$DIST_DIR/$APP_NAME.app" "$RELEASE_DIR/$APP_NAME.app"

ZIP_PATH="$RELEASE_DIR/${APP_NAME}_macOS.zip"
rm -f "$ZIP_PATH"
ditto -c -k --sequesterRsrc --keepParent "$RELEASE_DIR/$APP_NAME.app" "$ZIP_PATH"

echo "Build complete:"
echo "  App: $RELEASE_DIR/$APP_NAME.app"
echo "  Zip: $ZIP_PATH"
