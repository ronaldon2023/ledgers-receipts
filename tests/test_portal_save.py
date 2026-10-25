"""The portal's Save rules: POST /api/onboarding writes receipts-onboarding.json safely."""

import http.client
import http.server
import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from render.portal.__main__ import Handler

ROOT = Path(__file__).resolve().parent.parent
GOOD = {
    "approval_threshold_cents": 75000,
    "monthly_budget_cents": None,
    "approved_suppliers": ["Flour Co", "Dairy Barn"],
    "business_name": "Sweet Rose Bakery",
}


@pytest.fixture
def portal(tmp_path: Path) -> Iterator[tuple[int, Path]]:
    """A real portal server on a free port, saving into tmp_path."""
    Handler.business = tmp_path
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(
        target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    ).start()
    yield httpd.server_address[1], tmp_path
    httpd.shutdown()
    httpd.server_close()
    Handler.business = None


def post(port: int, body: object, origin: str | None = "self", ctype: str = "application/json"):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    headers = {"Content-Type": ctype, "Host": f"127.0.0.1:{port}"}
    if origin is not None:
        headers["Origin"] = f"http://127.0.0.1:{port}" if origin == "self" else origin
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    conn.request("POST", "/api/onboarding", data, headers)
    res = conn.getresponse()
    return res.status, json.loads(res.read() or b"{}")


def saved(folder: Path) -> dict:
    return json.loads((folder / "receipts-onboarding.json").read_text())


def test_save_creates_a_new_onboarding_file(portal: tuple[int, Path]) -> None:
    port, folder = portal
    assert post(port, GOOD) == (200, {"ok": True, "saved": "receipts-onboarding.json"})
    data = saved(folder)
    assert data["schema"] == "receipts-onboarding/0" and data["status"] == "portal"
    assert data["business"]["name"] == "Sweet Rose Bakery"
    rules = data["payment_rules"]
    assert rules["approval_threshold_cents"] == 75000 and rules["monthly_budget_cents"] is None
    assert rules["approved_suppliers"][1] == {
        "name": "Dairy Barn",
        "email_domain": None,
        "account_last4": None,
    }


def test_save_keeps_the_rest_of_an_existing_file(portal: tuple[int, Path]) -> None:
    port, folder = portal
    existing = {
        "schema": "receipts-onboarding/0",
        "status": "stub",
        "integrations": {"bookkeeping": "QuickBooks"},
        "payment_rules": {
            "approval_threshold_cents": 50000,
            "approved_suppliers": [
                {"name": "Flour Co", "email_domain": "flourco.example", "account_last4": "4471"}
            ],
        },
    }
    (folder / "receipts-onboarding.json").write_text(json.dumps(existing))
    assert post(port, GOOD)[0] == 200
    data = saved(folder)
    assert data["status"] == "stub" and data["integrations"] == {"bookkeeping": "QuickBooks"}
    flour = data["payment_rules"]["approved_suppliers"][0]
    assert flour == {"name": "Flour Co", "email_domain": "flourco.example", "account_last4": "4471"}
    assert data["payment_rules"]["approval_threshold_cents"] == 75000


@pytest.mark.parametrize(
    ("origin", "ctype", "status"),
    [
        (None, "application/json", 403),
        ("http://evil.example", "application/json", 403),
        ("self", "text/plain", 415),
    ],
)
def test_other_sites_and_non_json_are_refused(
    portal: tuple[int, Path], origin: str | None, ctype: str, status: int
) -> None:
    port, folder = portal
    assert post(port, GOOD, origin=origin, ctype=ctype)[0] == status
    assert not (folder / "receipts-onboarding.json").exists()


@pytest.mark.parametrize(
    "change",
    [
        {"approval_threshold_cents": 500.5},
        {"approval_threshold_cents": -1},
        {"approval_threshold_cents": True},
        {"monthly_budget_cents": "lots"},
        {"approved_suppliers": "Flour Co"},
        {"approved_suppliers": ["Acct 000123454471"]},
        {"approved_suppliers": ["x"] * 51},
    ],
)
def test_bad_values_are_refused(portal: tuple[int, Path], change: dict) -> None:
    port, folder = portal
    status, body = post(port, {**GOOD, **change})
    assert status == 400 and body["ok"] is False and body["error"]
    assert not (folder / "receipts-onboarding.json").exists()


def test_symlink_and_unreadable_file_are_not_overwritten(portal: tuple[int, Path]) -> None:
    port, folder = portal
    secret = folder / "secret.txt"
    secret.write_text("keep")
    (folder / "receipts-onboarding.json").symlink_to(secret)
    assert post(port, GOOD)[0] == 400
    assert secret.read_text() == "keep"
    (folder / "receipts-onboarding.json").unlink()
    (folder / "receipts-onboarding.json").write_text("{not json")
    assert post(port, GOOD)[0] == 400
    assert (folder / "receipts-onboarding.json").read_text() == "{not json"


def test_hooks_read_what_the_portal_saved(portal: tuple[int, Path]) -> None:
    port, folder = portal
    assert post(port, GOOD)[0] == 200
    env = {**os.environ, "RECEIPTS_ONBOARDING": str(folder / "receipts-onboarding.json")}
    env.pop("RECEIPTS_APPROVAL_CENTS", None)
    start = subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "session_start.py")],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    assert "onboarding answers on file" in start.stdout
    code = "import approve_payment as a; print(a.threshold_cents()[0])"
    gate = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=ROOT / "hooks",
        check=True,
    )
    assert gate.stdout.strip() == "75000"
