"""Minify static JS/CSS during production deploy (Render buildCommand)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "ygo_app" / "static"
TARGETS = (
    (STATIC / "js" / "app.js", "js"),
    (STATIC / "css" / "style.css", "css"),
)


def _minify_js(text: str) -> str:
    try:
        import rjsmin
    except ImportError:
        print("rjsmin not installed; skipping JS minify", file=sys.stderr)
        return text
    return rjsmin.jsmin(text)


def _minify_css(text: str) -> str:
    try:
        import csscompressor
    except ImportError:
        print("csscompressor not installed; skipping CSS minify", file=sys.stderr)
        return text
    return csscompressor.compress(text)


def main() -> int:
    for path, kind in TARGETS:
        if not path.is_file():
            print(f"skip missing {path}")
            continue
        original = path.read_text(encoding="utf-8")
        if kind == "js":
            compressed = _minify_js(original)
        else:
            compressed = _minify_css(original)
        path.write_text(compressed, encoding="utf-8")
        print(f"minified {path.name}: {len(original)} -> {len(compressed)} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
