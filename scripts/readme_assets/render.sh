#!/usr/bin/env bash
# Render the README/social images from the HTML sources in this directory.
# Requires Google Chrome. Run from the repo root:  bash scripts/readme_assets/render.sh
set -euo pipefail

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SRC="$(cd "$(dirname "$0")" && pwd)"
OUT="$SRC/../../docs/assets"
mkdir -p "$OUT"

shot() { # file.html WxH out.png
  "$CHROME" --headless --disable-gpu --hide-scrollbars \
    --screenshot="$OUT/$3" --window-size="$2" "file://$SRC/$1" 2>/dev/null
  echo "wrote docs/assets/$3"
}

shot social-preview.html 1280,640  social-preview.png
shot architecture.html   1560,880 architecture.png
shot workflow.html       1560,430  workflow.png
