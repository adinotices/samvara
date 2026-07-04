#!/usr/bin/env python3
"""Recompose the deployable bundle from frontend/src/ (see unpack_bundle.py).

Encodes src/app.html back into the JSON string the bundle runtime expects and
splices it into src/shell.html at the placeholder. '</' is escaped to '<\\/'
so the string can't terminate its surrounding <script> tag.

Usage:
  scripts/pack_bundle.py [src-dir] [out-bundle]    # defaults: frontend/src frontend/index.html
"""
from __future__ import annotations

import json
import os
import sys

PLACEHOLDER = "__SAMVARA_APP_JSON__"


def pack_to_string(src_dir: str) -> str:
    shell = open(os.path.join(src_dir, "shell.html"), encoding="utf-8").read()
    app = open(os.path.join(src_dir, "app.html"), encoding="utf-8").read()
    if shell.count(PLACEHOLDER) != 1:
        sys.exit(f"error: expected exactly one {PLACEHOLDER} in shell.html, "
                 f"found {shell.count(PLACEHOLDER)}")
    encoded = json.dumps(app, ensure_ascii=True).replace("</", "<\\/")
    json.loads(encoded)  # self-check: still valid JSON after the '</' escape
    return shell.replace(PLACEHOLDER, encoded)


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "frontend/src"
    out = sys.argv[2] if len(sys.argv) > 2 else "frontend/index.html"
    bundle = pack_to_string(src)
    with open(out, "w", encoding="utf-8") as f:
        f.write(bundle)
    print(f"packed {src}/ -> {out} ({len(bundle)} chars)")
