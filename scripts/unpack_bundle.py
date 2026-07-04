#!/usr/bin/env python3
"""Split the exported bundle into an editable source pair.

The design tool exports one 800KB single-line HTML file with the entire app
embedded as a JSON string inside <script type="__bundler/template">. That is
hostile to editing and to diffs, so we keep it unpacked in the repo instead:

  frontend/src/shell.html  the outer bundle (runtime, fonts, resource blobs)
                           with the app string replaced by a placeholder —
                           machine territory, never hand-edited
  frontend/src/app.html    the decoded inner document: ~1300 readable lines of
                           the app's actual HTML/JS — this is what you edit

pack_bundle.py reverses this losslessly (verified byte-identical round-trip).

Usage:
  scripts/unpack_bundle.py [bundle.html] [src-dir]     # defaults: frontend/index.html frontend/src

Re-importing a fresh export from the design tool:
  scripts/unpack_bundle.py ~/Downloads/export.html /tmp/fresh
  diff frontend/src/app.html /tmp/fresh/app.html      # then merge deliberately
The repo's source-level edits (OTP gate, boot error handling, …) live in
app.html, so a fresh export is merged there — never pasted over.
"""
from __future__ import annotations

import json
import re
import sys

PLACEHOLDER = "__SAMVARA_APP_JSON__"
TEMPLATE_RE = re.compile(
    r'(<script type="__bundler/template">\s*)(".*?")(\s*</script>)', re.S)


def unpack(bundle_path: str, src_dir: str) -> None:
    import os
    s = open(bundle_path, encoding="utf-8").read()
    m = TEMPLATE_RE.search(s)
    if not m:
        sys.exit(f"error: no __bundler/template script found in {bundle_path}")
    app = json.loads(m.group(2))
    shell = s[:m.start(2)] + PLACEHOLDER + s[m.end(2):]

    os.makedirs(src_dir, exist_ok=True)
    with open(os.path.join(src_dir, "shell.html"), "w", encoding="utf-8") as f:
        f.write(shell)
    with open(os.path.join(src_dir, "app.html"), "w", encoding="utf-8") as f:
        f.write(app)

    # Prove the pair reproduces the input byte-for-byte before declaring done.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from pack_bundle import pack_to_string
    if pack_to_string(src_dir) != s:
        sys.exit("error: round-trip mismatch — unpacked source does NOT "
                 "reproduce the bundle; nothing usable was written")
    print(f"unpacked {bundle_path} -> {src_dir}/shell.html + app.html "
          f"(round-trip verified)")


if __name__ == "__main__":
    bundle = sys.argv[1] if len(sys.argv) > 1 else "frontend/index.html"
    out = sys.argv[2] if len(sys.argv) > 2 else "frontend/src"
    unpack(bundle, out)
