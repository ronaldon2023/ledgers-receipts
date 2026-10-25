"""Singletons shared across auth/web.py's routes -- one AccountStore, one
LedgerAuth, and one ApiKeyStore instance, not one per request, so every
route sees the same registered passkeys and keys."""

from __future__ import annotations

import os

from auth.accounts import AccountStore
from auth.api_keys import ApiKeyStore
from auth.webauthn import LedgerAuth

RP_ID = os.environ.get("AUTH_RP_ID", "localhost")
ORIGIN = os.environ.get("AUTH_ORIGIN", "http://localhost:8430")

auth = LedgerAuth(rp_id=RP_ID, rp_name="Ledger", origin=ORIGIN)
accounts = AccountStore()
api_keys = ApiKeyStore()
