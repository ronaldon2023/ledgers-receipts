"""End-to-end tests for auth/web.py's signup, passkey-only sign-in, and
security (passkey management) pages, driven through a real FastAPI
TestClient against a real Fido2Server -- only the "browser" side
(navigator.credentials.create/get) is replaced, by
scripts.soft_authenticator.SoftAuthenticator, so every cryptographic step
the real pages rely on actually runs."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from auth import shared
from auth.web import build_auth_app
from scripts.soft_authenticator import SoftAuthenticator


@pytest.fixture(autouse=True)
def _isolated_stores(tmp_path, monkeypatch):
    """Point the shared singletons at a fresh on-disk store per test, and
    clear auth/web.py's in-memory ceremony/session state -- both are
    process-global, so without this tests would see each other's accounts
    and passkeys."""
    shared.accounts.path = tmp_path / "accounts.json"
    shared.auth.store.path = tmp_path / "credentials.json"

    import auth.web as web_module

    monkeypatch.setattr(web_module, "_pending_registrations", {})
    monkeypatch.setattr(web_module, "_pending_logins", {})
    monkeypatch.setattr(web_module, "_pending_added_passkeys", {})
    monkeypatch.setattr(web_module, "_sessions", {})


@pytest.fixture
def client():
    return TestClient(build_auth_app())


def _authenticator() -> SoftAuthenticator:
    return SoftAuthenticator(rp_id=shared.RP_ID, origin=shared.ORIGIN)


def _signup(client: TestClient, authenticator: SoftAuthenticator, display_name="Sweet Rose Bakery"):
    begin = client.post("/api/signup/begin", json={"display_name": display_name}).json()
    credential = authenticator.register_json(begin["options"]["publicKey"])
    complete = client.post(
        "/api/signup/complete",
        json={"registration_id": begin["registration_id"], "credential": credential},
    ).json()
    return complete


def _login(client: TestClient, authenticator: SoftAuthenticator):
    begin = client.post("/api/login/begin").json()
    credential = authenticator.authenticate_json(begin["options"]["publicKey"])
    complete = client.post(
        "/api/login/complete", json={"login_id": begin["login_id"], "credential": credential}
    ).json()
    return complete


def test_pages_render(client):
    for path in ("/", "/login", "/security"):
        assert client.get(path).status_code == 200


def test_signup_creates_account_and_session(client):
    complete = _signup(client, _authenticator())

    assert complete["display_name"] == "Sweet Rose Bakery"
    assert complete["session_token"]
    assert shared.accounts.by_id(complete["account_id"]) is not None
    assert len(shared.auth.store.for_account(complete["account_id"])) == 1


def test_login_with_registered_passkey(client):
    authenticator = _authenticator()
    signup = _signup(client, authenticator)

    login = _login(client, authenticator)

    assert login["account_id"] == signup["account_id"]
    assert login["session_token"]
    assert login["session_token"] != signup["session_token"]


def test_login_with_unregistered_passkey_is_rejected(client):
    _signup(client, _authenticator())
    stranger = _authenticator()

    begin = client.post("/api/login/begin").json()
    credential = stranger.authenticate_json(begin["options"]["publicKey"])
    response = client.post(
        "/api/login/complete", json={"login_id": begin["login_id"], "credential": credential}
    )

    assert response.status_code == 400


def test_security_page_requires_session(client):
    response = client.get("/api/security/passkeys")
    assert response.status_code == 401


def test_security_lists_the_passkey_from_signup(client):
    signup = _signup(client, _authenticator())

    response = client.get(
        "/api/security/passkeys", headers={"authorization": f"Bearer {signup['session_token']}"}
    )

    passkeys = response.json()["passkeys"]
    assert len(passkeys) == 1
    assert passkeys[0]["name"] == "Passkey 1"


def test_can_add_a_second_passkey(client):
    signup = _signup(client, _authenticator())
    headers = {"authorization": f"Bearer {signup['session_token']}"}
    second = _authenticator()

    begin = client.post("/api/security/passkeys/begin", headers=headers).json()
    credential = second.register_json(begin["options"]["publicKey"])
    added = client.post(
        "/api/security/passkeys/complete",
        json={"add_id": begin["add_id"], "credential": credential, "name": "Work laptop"},
    ).json()

    assert added["ok"] is True
    passkeys = client.get("/api/security/passkeys", headers=headers).json()["passkeys"]
    assert {p["name"] for p in passkeys} == {"Passkey 1", "Work laptop"}

    # The newly added passkey also signs in as the same account.
    login = _login(client, second)
    assert login["account_id"] == signup["account_id"]


def test_can_remove_a_passkey_but_not_the_last_one(client):
    signup = _signup(client, _authenticator())
    headers = {"authorization": f"Bearer {signup['session_token']}"}
    second = _authenticator()
    begin = client.post("/api/security/passkeys/begin", headers=headers).json()
    client.post(
        "/api/security/passkeys/complete",
        json={
            "add_id": begin["add_id"],
            "credential": second.register_json(begin["options"]["publicKey"]),
        },
    )

    passkeys = client.get("/api/security/passkeys", headers=headers).json()["passkeys"]
    assert len(passkeys) == 2
    first_id = passkeys[0]["credential_id"]

    removed = client.post(f"/api/security/passkeys/{first_id}/remove", headers=headers)
    assert removed.status_code == 200

    remaining = client.get("/api/security/passkeys", headers=headers).json()["passkeys"]
    assert len(remaining) == 1
    last_id = remaining[0]["credential_id"]

    blocked = client.post(f"/api/security/passkeys/{last_id}/remove", headers=headers)
    assert blocked.status_code == 400


def test_sessions_and_passkeys_are_isolated_per_account(client):
    alice = _signup(client, _authenticator(), display_name="Alice's Bakery")
    bob = _signup(client, _authenticator(), display_name="Bob's Bakery")

    alice_passkeys = client.get(
        "/api/security/passkeys", headers={"authorization": f"Bearer {alice['session_token']}"}
    ).json()["passkeys"]
    bob_passkeys = client.get(
        "/api/security/passkeys", headers={"authorization": f"Bearer {bob['session_token']}"}
    ).json()["passkeys"]

    assert len(alice_passkeys) == 1
    assert len(bob_passkeys) == 1
    assert alice_passkeys[0]["credential_id"] != bob_passkeys[0]["credential_id"]
