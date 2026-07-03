#!/usr/bin/env python3
"""Transform the raw Samvara bundle into a deployable index.html.

Two deterministic edits, no re-encoding of asset bytes:

  1. Remove the `apiClient` entry from the bundle's `ext_resources`. At boot the
     page builds `window.__resources` from those entries; with `apiClient` gone,
     `window.__resources.apiClient` is undefined and the app falls back to
     `import('./api-client.js')` — our real fetch client served next to this
     file. (We also drop the now-orphaned mock asset from the manifest so the
     dead code doesn't ship.)

  2. Inject `<script src="config.js"></script>` into the outer <head>, before
     the boot script. It runs at parse time and sets window.SAMVARA_CONFIG,
     which survives the document swap (it lives on window, not the DOM), so the
     real client can read apiBaseUrl / apiToken.

Usage: transform_bundle.py <src_html> <dst_html>
"""
from __future__ import annotations

import json
import re
import sys

CONFIG_TAG = '  <script src="config.js"></script>\n'


def _replace_tag_json(html: str, script_type: str, mutate) -> str:
    """Find <script type="{script_type}">…</script>, JSON-parse its body, pass it
    through `mutate`, and write the result back. Leaves surrounding whitespace."""
    pattern = re.compile(
        r'(<script type="' + re.escape(script_type) + r'">)(.*?)(</script>)',
        re.S,
    )
    m = pattern.search(html)
    if not m:
        raise SystemExit(f"transform: could not find <script type={script_type!r}>")
    body = m.group(2)
    data = json.loads(body)
    data = mutate(data)
    new_body = "\n" + json.dumps(data) + "\n"
    return html[:m.start()] + m.group(1) + new_body + m.group(3) + html[m.end():]


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: transform_bundle.py <src_html> <dst_html>")
    src, dst = sys.argv[1], sys.argv[2]
    html = open(src, encoding="utf-8").read()

    # Collect uuids referenced only by the apiClient id so we can drop the asset.
    ext_match = re.search(
        r'<script type="__bundler/ext_resources">(.*?)</script>', html, re.S)
    if not ext_match:
        raise SystemExit("transform: no ext_resources block found")
    ext = json.loads(ext_match.group(1))
    api_uuids = {e["uuid"] for e in ext if e.get("id") == "apiClient"}
    kept_uuids = {e["uuid"] for e in ext if e.get("id") != "apiClient"}
    orphan_uuids = api_uuids - kept_uuids  # safe to delete from manifest

    # 1a. Strip apiClient from ext_resources.
    html = _replace_tag_json(
        html, "__bundler/ext_resources",
        lambda arr: [e for e in arr if e.get("id") != "apiClient"],
    )

    # 1b. Drop the orphaned mock asset from the manifest.
    if orphan_uuids:
        html = _replace_tag_json(
            html, "__bundler/manifest",
            lambda man: {u: v for u, v in man.items() if u not in orphan_uuids},
        )

    # 2. Inject the config loader before the first </head> (outer document).
    if "config.js" not in html:
        idx = html.lower().find("</head>")
        if idx == -1:
            raise SystemExit("transform: no </head> in outer document")
        html = html[:idx] + CONFIG_TAG + html[idx:]

    # 3. Guard: refuse to ship a bundle that carries the mock auth gate or any
    # real email address. Catches a careless re-export of the raw bundle, which
    # would otherwise silently reintroduce them into the public site.
    for marker in ("Demo build", "demoCode", "ALLOWED_EMAIL", "ACCESS_RECIPIENT"):
        if marker in html:
            raise SystemExit(
                f"transform: forbidden marker {marker!r} found in bundle — "
                "the mock gate must be rewired to /v1/auth/* before deploy "
                "(see README: The frontend transform)."
            )
    addresses = {
        a for a in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", html)
        if not a.endswith(("example.com", "example.org", "example.net"))
    }
    if addresses:
        raise SystemExit(
            f"transform: {len(addresses)} real email address(es) found in the "
            "bundle — scrub them before deploy."
        )

    open(dst, "w", encoding="utf-8").write(html)

    print(f"transform: wrote {dst}")
    print(f"  ext_resources apiClient removed; "
          f"{len(orphan_uuids)} mock asset(s) dropped from manifest")
    print(f"  config.js loader injected into <head>")


if __name__ == "__main__":
    main()
