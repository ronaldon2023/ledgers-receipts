"""Sign up and sign in with a passkey -- no password anywhere, no account
id typed to sign in (a discoverable credential's `user_handle` says which
account it is).

Uses the browser's modern WebAuthn JSON helpers (`PublicKeyCredential
.parseCreationOptionsFromJSON` / `.toJSON()`), which line up with
python-fido2's own `dict(options)` / `*Response.from_dict` directly --
no manual base64url handling on either side.

Visual style (card/button/banner chrome, the color + type tokens) is
lifted from docs/mock/receipt.html so this reads as part of the same
product rather than a bolted-on admin form."""

from __future__ import annotations

import secrets
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fido2.webauthn import AuthenticationResponse, RegistrationResponse
from pydantic import BaseModel

from auth import shared
from auth.webauthn import WebAuthnError

# Short-lived, in-memory, process-local state -- fine for a ceremony that
# starts and finishes within one browser tab's lifetime; nothing here
# needs to survive a server restart.
_pending_registrations: dict[str, dict] = {}
_pending_logins: dict[str, dict] = {}

# session_token -> account_id, issued at sign-in.
_sessions: dict[str, str] = {}


def build_auth_app() -> FastAPI:
    app = FastAPI(title="The Ledger — Account")

    @app.get("/", response_class=HTMLResponse)
    def signup_page() -> str:
        return _SIGNUP_HTML

    @app.get("/login", response_class=HTMLResponse)
    def login_page() -> str:
        return _LOGIN_HTML

    @app.post("/api/signup/begin")
    def signup_begin(body: _SignupBeginRequest) -> dict:
        account_id = f"acct-{uuid.uuid4().hex[:12]}"
        options, state = shared.auth.register_begin(account_id, body.display_name)
        registration_id = uuid.uuid4().hex
        _pending_registrations[registration_id] = {
            "account_id": account_id,
            "display_name": body.display_name,
            "fido_state": state,
        }
        return {"registration_id": registration_id, "options": dict(options)}

    @app.post("/api/signup/complete")
    def signup_complete(body: _SignupCompleteRequest) -> dict:
        reg = _pending_registrations.pop(body.registration_id, None)
        if reg is None:
            raise HTTPException(400, "unknown or expired registration")
        try:
            response = RegistrationResponse.from_dict(body.credential)
            shared.auth.register_complete(reg["account_id"], reg["fido_state"], response)
        except Exception as exc:  # noqa: BLE001 - surface the real reason to the owner
            raise HTTPException(400, f"passkey registration failed: {exc}") from None
        account = shared.accounts.create(reg["display_name"], account_id=reg["account_id"])
        session_token = secrets.token_urlsafe(32)
        _sessions[session_token] = account.account_id
        return {
            "account_id": account.account_id,
            "display_name": account.display_name,
            "session_token": session_token,
        }

    @app.post("/api/login/begin")
    def login_begin() -> dict:
        import os

        challenge = os.urandom(32)
        options, state = shared.auth.authenticate_begin_discoverable(challenge)
        login_id = uuid.uuid4().hex
        _pending_logins[login_id] = {"fido_state": state}
        return {"login_id": login_id, "options": dict(options)}

    @app.post("/api/login/complete")
    def login_complete(body: _LoginCompleteRequest) -> dict:
        login = _pending_logins.pop(body.login_id, None)
        if login is None:
            raise HTTPException(400, "unknown or expired sign-in attempt")
        try:
            response = AuthenticationResponse.from_dict(body.credential)
            account_id, _ = shared.auth.authenticate_complete_discoverable(
                login["fido_state"], response
            )
        except WebAuthnError as exc:
            raise HTTPException(400, f"passkey sign-in failed: {exc}") from None
        account = shared.accounts.by_id(account_id)
        if account is None:
            raise HTTPException(400, "passkey is registered but the account no longer exists")
        session_token = secrets.token_urlsafe(32)
        _sessions[session_token] = account_id
        return {
            "session_token": session_token,
            "account_id": account.account_id,
            "display_name": account.display_name,
        }

    return app


class _SignupBeginRequest(BaseModel):
    display_name: str


class _SignupCompleteRequest(BaseModel):
    registration_id: str
    credential: dict


class _LoginCompleteRequest(BaseModel):
    login_id: str
    credential: dict


_STYLE = """
:root{
  --paper:#fbfbf9; --ink:#1d2430; --muted:#5d6675; --rule:#d9dde3; --panel:#f1f3f6;
  --card:#ffffff; --ok:#1f7a4d; --ok-bg:#e3f2ea; --bad:#b42318; --bad-bg:#fbe9e7;
  --accent:#1d2430; --accent-ink:#fbfbf9;
  --shadow:0 1px 2px rgba(20,24,30,.04), 0 12px 28px -8px rgba(20,24,30,.12);
  --serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --paper:#14181e; --ink:#e7eaef; --muted:#9aa3b2; --rule:#2c333d; --panel:#1b2028;
  --card:#1a1f27; --ok:#5cc58f; --ok-bg:#16301f; --bad:#ff8a7a; --bad-bg:#3a1714;
  --accent:#e7eaef; --accent-ink:#14181e;
  --shadow:0 1px 2px rgba(0,0,0,.3), 0 12px 28px -8px rgba(0,0,0,.5); color-scheme:dark}}
:root[data-theme="dark"]{
  --paper:#14181e; --ink:#e7eaef; --muted:#9aa3b2; --rule:#2c333d; --panel:#1b2028;
  --card:#1a1f27; --ok:#5cc58f; --ok-bg:#16301f; --bad:#ff8a7a; --bad-bg:#3a1714;
  --accent:#e7eaef; --accent-ink:#14181e;
  --shadow:0 1px 2px rgba(0,0,0,.3), 0 12px 28px -8px rgba(0,0,0,.5); color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--paper);color:var(--ink);font:15px/1.5 var(--sans);margin:0;
  min-height:100vh;display:grid;align-items:center;justify-content:center;
  padding:max(24px,env(safe-area-inset-top,0px)) 20px max(24px,env(safe-area-inset-bottom,0px))}
.card{width:min(440px,100%);background:var(--card);border:1px solid var(--rule);border-radius:18px;
  box-shadow:var(--shadow);padding:32px 30px;display:grid;gap:18px}
.eyebrow{font:600 12px/1 var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
h1{font:600 26px/1.2 var(--serif);margin:0;text-wrap:balance}
.lede{margin:0;color:var(--muted)}
label{display:block;font:600 13px var(--sans);color:var(--muted);margin-bottom:6px}
input[type=text]{width:100%;padding:11px 13px;font:15px var(--sans);color:var(--ink);
  background:var(--panel);border:1px solid var(--rule);border-radius:10px;outline:none}
input[type=text]:focus{border-color:var(--ink);box-shadow:0 0 0 3px color-mix(in srgb, var(--ink) 12%, transparent)}
.btn{display:flex;align-items:center;justify-content:center;gap:8px;width:100%;padding:13px 18px;
  font:600 15px var(--sans);color:var(--accent-ink);background:var(--accent);border:none;
  border-radius:10px;cursor:pointer;transition:opacity .15s,transform .1s}
.btn:hover{opacity:.9}
.btn:active{transform:scale(.99)}
.btn:disabled{opacity:.55;cursor:default}
.btn.loading .spin{display:inline-block}
.btn .spin{display:none;width:15px;height:15px;border-radius:50%;
  border:2px solid color-mix(in srgb, var(--accent-ink) 35%, transparent);
  border-top-color:var(--accent-ink);animation:spin .7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.banner{display:none;border-radius:10px;padding:12px 14px;font-size:13.5px;gap:8px;align-items:flex-start}
.banner.show{display:flex}
.banner.bad{background:var(--bad-bg);color:var(--bad)}
.banner.ok{background:var(--ok-bg);color:var(--ok)}
.hint{font-size:12.5px;color:var(--muted);margin:0}
.center{display:grid;gap:14px;text-align:center}
a{color:var(--ink)}
"""


def _page(title: str, body: str, extra_script: str = "") -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title} — The Ledger</title><style>{_STYLE}</style></head>
<body><main class="card">
<span class="eyebrow">The Ledger</span>
{body}
</main>
<script>{extra_script}</script>
</body></html>"""


_SIGNUP_BODY = """
<h1>Create your account</h1>
<p class="lede">Register a passkey — no password to pick or remember.</p>
<div>
  <label for="name">Your name or business name</label>
  <input type="text" id="name" placeholder="Sweet Rose Bakery">
</div>
<button class="btn" id="go"><span class="spin"></span><span class="label">Register passkey</span></button>
<div class="banner bad" id="error"></div>
<p class="hint center">Already have an account? <a href="/login">Sign in</a></p>
"""

_SIGNUP_SCRIPT = """
const go = document.getElementById('go');
const error = document.getElementById('error');
go.onclick = async () => {
  error.classList.remove('show');
  go.classList.add('loading');
  go.disabled = true;
  try {
    const display_name = document.getElementById('name').value || 'Owner';
    const begin = await fetch('/api/signup/begin', {method:'POST', headers:{'content-type':'application/json'},
      body: JSON.stringify({display_name})}).then(r => r.json());
    const options = PublicKeyCredential.parseCreationOptionsFromJSON(begin.options.publicKey);
    const credential = await navigator.credentials.create({publicKey: options});
    const complete = await fetch('/api/signup/complete', {method:'POST', headers:{'content-type':'application/json'},
      body: JSON.stringify({registration_id: begin.registration_id, credential: credential.toJSON()})}).then(r => r.json());
    if (!complete.session_token) throw new Error(complete.detail || JSON.stringify(complete));
    sessionStorage.setItem('ledger_session', complete.session_token);
    window.location.href = '/login';
  } catch (err) {
    error.textContent = "Couldn't register: " + (err.message || err);
    error.classList.add('show');
  } finally {
    go.classList.remove('loading');
    go.disabled = false;
  }
};
"""

_SIGNUP_HTML = _page("Sign up", _SIGNUP_BODY, _SIGNUP_SCRIPT)


_LOGIN_BODY = """
<h1>Sign in</h1>
<p class="lede">Sign in with the passkey you registered. No password, nothing to type first.</p>
<button class="btn" id="go"><span class="spin"></span><span class="label">Sign in with passkey</span></button>
<div class="banner bad" id="error"></div>
<p class="hint center">No account yet? <a href="/">Sign up</a></p>
"""

_LOGIN_SCRIPT = """
const go = document.getElementById('go');
const error = document.getElementById('error');
go.onclick = async () => {
  error.classList.remove('show');
  go.classList.add('loading');
  go.disabled = true;
  try {
    const begin = await fetch('/api/login/begin', {method: 'POST'}).then(r => r.json());
    const options = PublicKeyCredential.parseRequestOptionsFromJSON(begin.options.publicKey);
    const credential = await navigator.credentials.get({publicKey: options});
    const complete = await fetch('/api/login/complete', {method: 'POST',
      headers: {'content-type': 'application/json'},
      body: JSON.stringify({login_id: begin.login_id, credential: credential.toJSON()})})
      .then(r => r.json());
    if (!complete.session_token) throw new Error(complete.detail || JSON.stringify(complete));
    sessionStorage.setItem('ledger_session', complete.session_token);
  } catch (err) {
    error.textContent = "Couldn't sign in: " + (err.message || err);
    error.classList.add('show');
  } finally {
    go.classList.remove('loading');
    go.disabled = false;
  }
};
"""

_LOGIN_HTML = _page("Sign in", _LOGIN_BODY, _LOGIN_SCRIPT)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(build_auth_app(), host="127.0.0.1", port=8430)
