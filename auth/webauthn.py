"""WebAuthn registration and passkey-only sign-in, backed by python-fido2.

Registration requests a resident/discoverable credential, which is what
lets sign-in work from the passkey alone -- no account id or password
typed first; the assertion's `user_handle` says which account it is
(see `authenticate_begin_discoverable` / `account_id_from_discoverable_response`).

`CredentialStore` persists `{credential_id, public_key, name, sign_count,
created_at, last_used_at, attachment}` per account -- not just the raw
credential, so a "your passkeys" settings page (name, type, when added,
last used) and real rename/remove flows are just reads/writes on this
store, not something layered on top. Every field but the three identity
ones (`account_id`, `credential_id_b64`, `raw_hex`) has a default, and
`from_dict` ignores unknown keys: a record written by an older or newer
version of this schema still loads instead of taking the whole store
down (see `StoredCredential.from_dict`)."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fido2.server import Fido2Server
from fido2.utils import websafe_encode
from fido2.webauthn import (
    AttestedCredentialData,
    AuthenticationResponse,
    PublicKeyCredentialRpEntity,
    PublicKeyCredentialUserEntity,
    RegistrationResponse,
    ResidentKeyRequirement,
)

DEFAULT_CREDENTIAL_STORE_PATH = Path("logs/credentials.json")

# Shown verbatim to whoever is signing in -- never reveal *why* a passkey
# didn't work (unknown account vs. wrong credential vs. bad signature):
# that's an account-enumeration leak (WebAuthn spec, section 14.6.2). Public
# (no leading underscore) so callers outside this module, e.g. auth/web.py's
# "the account itself is gone" case, can reuse the exact same wording.
GENERIC_SIGNIN_ERROR = (
    "We couldn't sign you in with that passkey. Try again, pick a different "
    "one if your device offered more than one, or register a new passkey."
)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class WebAuthnError(Exception):
    """Raised when registration or an assertion fails verification, or when
    an account has no registered passkey to check against."""


@dataclass(frozen=True, slots=True)
class StoredCredential:
    account_id: str
    credential_id_b64: str
    raw_hex: str
    name: str = "Passkey"
    sign_count: int = 0
    created_at: str = field(default_factory=_now)
    last_used_at: str | None = None
    # "platform" (Touch ID/Face ID/Windows Hello) or "cross-platform"
    # (a security key or another device) -- whatever the browser reported
    # at registration; None for older records that predate this field.
    attachment: str | None = None

    def attested(self) -> AttestedCredentialData:
        return AttestedCredentialData(bytes.fromhex(self.raw_hex))

    def device_label(self) -> str:
        return {"platform": "This device", "cross-platform": "Security key or other device"}.get(
            self.attachment or "", "Unknown device"
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> StoredCredential:
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


class CredentialStore:
    """Only this class writes `logs/credentials.json`."""

    def __init__(self, path: Path = DEFAULT_CREDENTIAL_STORE_PATH) -> None:
        self.path = path

    def _load(self) -> list[StoredCredential]:
        if not self.path.exists():
            return []
        return [StoredCredential.from_dict(d) for d in json.loads(self.path.read_text())]

    def _save(self, records: list[StoredCredential]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([r.to_dict() for r in records], indent=2, sort_keys=True))

    def for_account(self, account_id: str) -> list[StoredCredential]:
        return [r for r in self._load() if r.account_id == account_id]

    def by_credential_id(self, credential_id_b64: str) -> StoredCredential | None:
        return next((r for r in self._load() if r.credential_id_b64 == credential_id_b64), None)

    def add(
        self,
        account_id: str,
        attested: AttestedCredentialData,
        name: str | None = None,
        attachment: str | None = None,
    ) -> StoredCredential:
        existing_count = len(self.for_account(account_id))
        record = StoredCredential(
            account_id=account_id,
            credential_id_b64=websafe_encode(attested.credential_id),
            raw_hex=bytes(attested).hex(),
            name=name or f"Passkey {existing_count + 1}",
            attachment=attachment,
        )
        records = self._load()
        records.append(record)
        self._save(records)
        return record

    def record_use(self, credential_id_b64: str, new_sign_count: int) -> None:
        records = self._load()
        for i, r in enumerate(records):
            if r.credential_id_b64 == credential_id_b64:
                records[i] = StoredCredential(
                    **{**r.to_dict(), "sign_count": new_sign_count, "last_used_at": _now()}
                )
        self._save(records)

    def rename(self, account_id: str, credential_id_b64: str, name: str) -> bool:
        records = self._load()
        found = False
        for i, r in enumerate(records):
            if r.account_id == account_id and r.credential_id_b64 == credential_id_b64:
                records[i] = StoredCredential(**{**r.to_dict(), "name": name})
                found = True
        if found:
            self._save(records)
        return found

    def remove(self, account_id: str, credential_id_b64: str) -> bool:
        records = self._load()
        kept = [
            r
            for r in records
            if not (r.account_id == account_id and r.credential_id_b64 == credential_id_b64)
        ]
        if len(kept) == len(records):
            return False
        self._save(kept)
        return True


class LedgerAuth:
    """Thin wrapper around `fido2.server.Fido2Server` scoped to one
    relying-party origin -- passkeys are origin-bound, so this must be
    constructed with the app's own real origin, not a placeholder."""

    def __init__(
        self, rp_id: str, rp_name: str, origin: str, store: CredentialStore | None = None
    ) -> None:
        self.rp_id = rp_id
        self.origin = origin
        self.server = Fido2Server(PublicKeyCredentialRpEntity(id=rp_id, name=rp_name))
        self.store = store or CredentialStore()

    def register_begin(self, account_id: str, display_name: str) -> tuple[Any, Any]:
        existing = [r.attested() for r in self.store.for_account(account_id)]
        user = PublicKeyCredentialUserEntity(
            id=account_id.encode(), name=display_name, display_name=display_name
        )
        # PREFERRED, not REQUIRED: a discoverable (resident) credential is
        # what lets passkey-only sign-in work, but REQUIRED would hard-fail
        # on any authenticator that doesn't support resident keys -- a
        # worse failure mode than falling back to a non-resident one.
        return self.server.register_begin(
            user, credentials=existing, resident_key_requirement=ResidentKeyRequirement.PREFERRED
        )

    def register_complete(
        self,
        account_id: str,
        state: Any,
        response: RegistrationResponse,
        name: str | None = None,
        attachment: str | None = None,
    ) -> StoredCredential:
        auth_data = self.server.register_complete(state, response)
        return self.store.add(
            account_id, auth_data.credential_data, name=name, attachment=attachment
        )

    def authenticate_begin_discoverable(self, challenge: bytes) -> tuple[Any, Any]:
        """Passkey-only sign-in: no account id typed first. Passing no
        credential list lets the browser offer any discoverable passkey
        registered for this origin; which account that turns out to be
        isn't known until the assertion comes back with a `user_handle`."""
        return self.server.authenticate_begin(credentials=None, challenge=challenge)

    def authenticate_complete_discoverable(
        self, state: Any, response: AuthenticationResponse
    ) -> tuple[str, StoredCredential]:
        # Every failure past this point -- unknown account, no matching
        # credential, a bad signature -- raises the same generic message.
        # Telling them apart would let a caller probe which accounts exist.
        account_id = account_id_from_discoverable_response(response)
        stored = self.store.for_account(account_id)
        creds = [r.attested() for r in stored]
        if not creds:
            raise WebAuthnError(GENERIC_SIGNIN_ERROR)
        try:
            verified = self.server.authenticate_complete(state, creds, response)
        except Exception as exc:
            raise WebAuthnError(GENERIC_SIGNIN_ERROR) from exc
        matching = next(
            (r for r in stored if r.attested().credential_id == verified.credential_id), None
        )
        if matching is None:
            raise WebAuthnError(GENERIC_SIGNIN_ERROR)

        new_counter = response.response.authenticator_data.counter
        if new_counter != 0 and matching.sign_count != 0 and new_counter <= matching.sign_count:
            raise WebAuthnError("sign counter did not increase — possible cloned credential")
        self.store.record_use(matching.credential_id_b64, new_counter)
        return account_id, self.store.by_credential_id(matching.credential_id_b64)


def account_id_from_discoverable_response(response: AuthenticationResponse) -> str:
    """The account this assertion claims to be, from its `user_handle` --
    which, for a passkey this app never registered (a different RP's
    passkey the browser's own picker happened to also offer for this RP
    ID), can be missing or not even valid UTF-8. Both are routine "wrong
    passkey" cases, not a bug, and get the same generic sign-in error as
    any other mismatch -- see `authenticate_complete_discoverable`."""
    user_handle = response.response.user_handle
    if not user_handle:
        raise WebAuthnError(GENERIC_SIGNIN_ERROR)
    try:
        return user_handle.decode()
    except UnicodeDecodeError:
        raise WebAuthnError(GENERIC_SIGNIN_ERROR) from None
