#!/usr/bin/env bash
# Build the static frontend into dist/ for GitHub Pages (or any static host).
#
#   - transforms frontend/index.html (the raw bundle) so it loads the REAL
#     ./api-client.js instead of the bundled mock,
#   - copies api-client.js and config.js next to it,
#   - adds .nojekyll (so GitHub Pages serves files starting with _ and doesn't
#     run Jekyll) and, if a domain is set, a CNAME.
#
# Usage:
#   scripts/build-frontend.sh                 # uses frontend/config.js if present
#   CNAME=samvara.app scripts/build-frontend.sh
#
# Requires: python3 (already present on GitHub Actions runners).

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/frontend"
OUT="$ROOT/dist"

rm -rf "$OUT"
mkdir -p "$OUT"

# 1. Transform the bundle → dist/index.html
python3 "$ROOT/scripts/transform_bundle.py" "$SRC/index.html" "$OUT/index.html"

# 2. Real API client
cp "$SRC/api-client.js" "$OUT/api-client.js"

# 3. Config: prefer a real config.js, fall back to the example with a warning.
if [ -f "$SRC/config.js" ]; then
  cp "$SRC/config.js" "$OUT/config.js"
  echo "build: using frontend/config.js"
else
  cp "$SRC/config.example.js" "$OUT/config.js"
  echo "build: WARNING — no frontend/config.js found; shipped config.example.js."
  echo "       Set apiBaseUrl/apiToken for your environment before going live."
fi

# 4. GitHub Pages niceties
touch "$OUT/.nojekyll"
if [ -n "${CNAME:-}" ]; then
  echo "$CNAME" > "$OUT/CNAME"
  echo "build: wrote CNAME ($CNAME)"
fi

echo "build: dist/ ready:"
ls -la "$OUT"
