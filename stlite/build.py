"""Build the stlite (in-browser) version of the app into a static folder.

    python stlite/build.py [--out _site] [--serve]
    python -m http.server 8601 -d _site

The Community Cloud app is not touched: this copies its files and patches only the copy
(the model "race" pacing, which needs `await asyncio.sleep` in stlite).
"""

import argparse
import importlib.metadata as md
import json
import shutil
import tomllib
from pathlib import Path

STLITE_VERSION = "1.12.3"
ROOT = Path(__file__).resolve().parent.parent

APP_PY = [
    "streamlit_app.py", "calls.py", "charts.py", "click_hint.py", "costs.py", "demo_data.py",
    "explain.py", "grow_waterfall.py", "mobile_nav.py", "move_markers.py", "pilot.py",
    "rule_game.py", "weekly.py",
]
APP_DIRS = ["data"]
APP_FILES = [  # config.toml goes in via streamlitConfig instead
    "style.css",
    "resources/Chalky HSMA-07-wide white logo tall with tagline - new tagline.png",
    "resources/NIHR_APPLIED_RESEARCH_COLLABORATION_Logo_Horizontal_RGB_WHITE.png",
    "resources/hsma_qr.png",
    "resources/fonts/hsma-display/HSMADisplay-Regular.woff2",
]

# time.sleep is a no-op in stlite; top-level `await asyncio.sleep` paces the race frames instead.
# (Using await in the original file would be a SyntaxError on Community Cloud.)
SLEEP_OLD = "time.sleep(2.0 if i == at else 0.4 if flat else 0.9)"
SLEEP_NEW = "await asyncio.sleep(2.0 if i == at else 0.4 if flat else 0.9)"


def flatten(d: dict, prefix="") -> dict:
    flat = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        flat.update(flatten(v, key + ".") if isinstance(v, dict) else {key: v})
    return flat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "_site"))
    ap.add_argument("--serve", action="store_true", help="after building, serve the site locally (Ctrl+C to stop)")
    ap.add_argument("--port", type=int, default=8601)
    args = ap.parse_args()
    out = Path(args.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    for name in APP_PY + APP_FILES:
        (out / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / name, out / name)
    for name in APP_DIRS:
        shutil.copytree(ROOT / name, out / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    # Only the copy is patched (the app's own files stay as they are)
    entry = out / "streamlit_app.py"
    src = entry.read_text(encoding="utf8")
    assert src.count(SLEEP_OLD) == 1, "streamlit_app.py changed: update SLEEP_OLD in stlite/build.py"
    src = src.replace(SLEEP_OLD, SLEEP_NEW)
    entry.write_text("import asyncio  # stlite build only\n" + src, encoding="utf8")

    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    config = flatten(tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf8")))
    # stlite 1.12.3 crashes (react-helmet) on a theme.font that carries a font URL. style.css
    # already applies the family, so only the download is needed: load it from index.html.
    font = config.pop("theme.font", "")
    font_url = font.split(":", 1)[1].rsplit(",", 1)[0].strip() if ":http" in font else ""
    options = {
        "entrypoint": "streamlit_app.py",
        "files": {f: {"url": f} for f in files},
        # matplotlib ships with Pyodide but is only loaded if listed; plotly is not shipped
        "requirements": [f"plotly=={md.version('plotly')}", "matplotlib"],
        "streamlitConfig": config,
    }
    html = (ROOT / "stlite" / "index.html").read_text(encoding="utf8")
    html = html.replace("__STLITE_VERSION__", STLITE_VERSION).replace("__MOUNT_OPTIONS__", json.dumps(options, indent=2))
    html = html.replace("__FONT_LINK__", f'<link rel="stylesheet" href="{font_url}" />' if font_url else "")
    (out / "index.html").write_text(html, encoding="utf8")
    (out / ".nojekyll").write_text("")
    print(f"Built {len(files)} files into {out}")
    print(f"Preview: python -m http.server {args.port} -d {out}")
    if args.serve:
        serve(out, args.port)


def serve(out: Path, port: int):
    """Plain static server. stlite can't run from file://."""
    import functools
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class NoCacheHandler(SimpleHTTPRequestHandler):
        # stlite fetches the app's files through the browser cache, so without this a rebuild,
        # or another app previewed earlier on the same port, can be served stale
        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

    handler = functools.partial(NoCacheHandler, directory=str(out))
    with ThreadingHTTPServer(("127.0.0.1", port), handler) as server:
        print(f"Serving http://localhost:{port}/ (first load takes 20-60 s; Ctrl+C to stop)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("Stopped")


if __name__ == "__main__":
    main()
