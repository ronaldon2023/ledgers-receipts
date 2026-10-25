"""Serve the owner portal on localhost. Run with: python -m render.portal [--port 8000]

Serves only the portal files and, under /data/, the JSON in fixtures/portal/.
Nothing else in the repo (bakery.db, logs) is reachable.
"""

import argparse
import http.server
import webbrowser
from pathlib import Path
from urllib.parse import unquote, urlsplit

HERE = Path(__file__).resolve().parent
DATA = HERE.parent.parent / "fixtures" / "portal"
SERVED = {".html", ".css", ".js", ".json"}


def resolve(url_path: str, here: Path = HERE, data: Path = DATA) -> Path | None:
    """Map a URL path to a file the portal may serve, or None if it is off limits."""
    path = unquote(urlsplit(url_path).path)
    root, rest = (data, path[len("/data/") :]) if path.startswith("/data/") else (here, path)
    target = (root / rest.lstrip("/")).resolve()
    if target == root:
        target = root / "index.html"
    if root not in target.parents or target.suffix not in SERVED or not target.is_file():
        return None
    return target


class Handler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        target = resolve(path)
        return str(target) if target else str(HERE / "__not_found__")

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def serve(port: int = 8000, open_browser: bool = True) -> None:
    """Serve the portal on 127.0.0.1 until interrupted."""
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler) as httpd:
        url = f"http://127.0.0.1:{port}/"
        print(f"Owner portal at {url} (Ctrl+C to stop)")
        if open_browser:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the Receipts owner portal on localhost.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    args = parser.parse_args()
    serve(args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
