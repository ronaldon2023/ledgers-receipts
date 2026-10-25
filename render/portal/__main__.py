"""Serve the owner portal on localhost. Run with: python -m render.portal [--port 8000]

Serves only the portal files and, under /data/, the JSON in fixtures/portal/, plus
/data/onboarding.json: the business folder's receipts-onboarding.json, which the Claude Code
onboarding skill writes. Nothing else in the repo or the business folder is reachable.

POST /api/onboarding saves the owner's payment rules from the portal's "Your rules" step into
that same file (see rules.py). It accepts only JSON sent by the portal page itself.
"""

import argparse
import http.server
import json
import webbrowser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from render.portal.rules import parse_rules, save

HERE = Path(__file__).resolve().parent
DATA = HERE.parent.parent / "fixtures" / "portal"
SERVED = {".html", ".css", ".js", ".json"}
ONBOARDING = "receipts-onboarding.json"
ONBOARDING_URL = "/data/onboarding.json"
SAVE_URL = "/api/onboarding"
MAX_BODY = 16 * 1024


def host_allowed(host: str | None, port: int) -> bool:
    """Only this machine's own names: a page on another site that points its domain at
    127.0.0.1 (DNS rebinding) sends its own Host, so it can't read the owner's rules."""
    return host in (f"127.0.0.1:{port}", f"localhost:{port}")


def origin_allowed(origin: str | None, port: int) -> bool:
    """Only the portal page itself may save: a form or script on any other site sends its own
    Origin (or none), so it can't change the owner's approval amount."""
    return origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")


def resolve(
    url_path: str, here: Path = HERE, data: Path = DATA, business: Path | None = None
) -> Path | None:
    """Map a URL path to a file the portal may serve, or None if it is off limits."""
    path = unquote(urlsplit(url_path).path)
    if path == ONBOARDING_URL:
        try:
            folder = (business or Path.cwd()).resolve()
            target = (folder / ONBOARDING).resolve()  # a symlink must not lead anywhere else
        except (OSError, RuntimeError):  # a symlink loop raises RuntimeError before Python 3.13
            return None
        return (
            target
            if target.parent == folder and target.name == ONBOARDING and target.is_file()
            else None
        )
    root, rest = (data, path[len("/data/") :]) if path.startswith("/data/") else (here, path)
    target = (root / rest.lstrip("/")).resolve()
    if target == root:
        target = root / "index.html"
    if root not in target.parents or target.suffix not in SERVED or not target.is_file():
        return None
    return target


class Handler(http.server.SimpleHTTPRequestHandler):
    business: Path | None = None  # folder holding receipts-onboarding.json; None means cwd

    def translate_path(self, path: str) -> str:
        target = resolve(path, business=self.business)
        return str(target) if target else str(HERE / "__not_found__")

    def answered(self) -> bool:
        """Answer requests the file server shouldn't: other hosts, and no onboarding file yet."""
        if not host_allowed(self.headers.get("Host"), self.server.server_address[1]):
            self.send_error(403, "Open the portal at 127.0.0.1 or localhost")
            return True
        if self.path.split("?")[0] == ONBOARDING_URL and not resolve(
            self.path, business=self.business
        ):
            self.send_response(204)  # not onboarded yet: empty, so the browser logs no error
            self.end_headers()
            return True
        return False

    def do_GET(self) -> None:
        if not self.answered():
            super().do_GET()

    def do_HEAD(self) -> None:
        if not self.answered():
            super().do_HEAD()

    def reply(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        """Save the owner's payment rules. Every refusal says why, and writes nothing."""
        port = self.server.server_address[1]
        if not host_allowed(self.headers.get("Host"), port):
            return self.reply(
                403, {"ok": False, "error": "Open the portal at 127.0.0.1 or localhost"}
            )
        if urlsplit(self.path).path != SAVE_URL:
            return self.reply(404, {"ok": False, "error": "Not found"})
        if not origin_allowed(self.headers.get("Origin"), port):
            return self.reply(403, {"ok": False, "error": "Only the portal page can save rules"})
        if self.headers.get_content_type() != "application/json":
            return self.reply(415, {"ok": False, "error": "Send the rules as JSON"})
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self.reply(411, {"ok": False, "error": "Content-Length is required"})
        if not 0 < length <= MAX_BODY:
            return self.reply(413, {"ok": False, "error": "The request is too large"})
        try:
            rules = parse_rules(self.rfile.read(length))
            target = save(self.business or Path.cwd(), rules)
        except ValueError as e:
            return self.reply(400, {"ok": False, "error": str(e)})
        except OSError:
            return self.reply(500, {"ok": False, "error": "The rules couldn't be saved"})
        self.reply(200, {"ok": True, "saved": target.name})

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def serve(port: int = 8000, open_browser: bool = True, business: Path | None = None) -> None:
    """Serve the portal on 127.0.0.1 until interrupted."""
    Handler.business = business
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
    parser.add_argument(
        "--business-dir",
        type=Path,
        help=f"folder with the owner's {ONBOARDING} (default: the current folder)",
    )
    args = parser.parse_args()
    serve(args.port, open_browser=not args.no_browser, business=args.business_dir)


if __name__ == "__main__":
    main()
