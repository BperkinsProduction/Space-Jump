#!/bin/sh
# Xcode build phase: copy the Cloud Hopper web game (the repo root, one folder up) into the app
# bundle's Game/ folder, wired to the bundled three.js in vendor/ so the app runs offline.
#
# WebKit ignores import maps on custom-scheme pages (the app serves cloudhopper://game/...), so the
# bare 'three' / 'three/addons/' specifiers are rewritten to relative paths instead.
set -e
GAME_SRC="${SRCROOT}/.."
DEST="${TARGET_BUILD_DIR}/${UNLOCALIZED_RESOURCES_FOLDER_PATH}/Game"
mkdir -p "$DEST/models" "$DEST/textures" "$DEST/vendor/three"

if ! grep -q 'cdn.jsdelivr.net/npm/three@0.160.0/' "$GAME_SRC/index.html"; then
  echo "error: index.html no longer loads three.js 0.160.0; update ios/vendor/three and this script." >&2
  exit 1
fi
sed -e "s#from 'three'#from './vendor/three/build/three.module.js'#g" \
    -e "s#from 'three/addons/#from './vendor/three/examples/jsm/#g" \
    "$GAME_SRC/index.html" > "$DEST/index.html"

rsync -a --delete --include='*.glb' --exclude='*' "$GAME_SRC/models/" "$DEST/models/"
rsync -a --delete "$GAME_SRC/textures/" "$DEST/textures/"
rsync -a --delete "${SRCROOT}/vendor/three/" "$DEST/vendor/three/"
# add-ons all sit at vendor/three/examples/jsm/<folder>/<file>.js
find "$DEST/vendor/three/examples/jsm" -name '*.js' -exec sed -i '' "s#from 'three'#from '../../../build/three.module.js'#g" {} +
