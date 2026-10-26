"""API keys -- the bearer credential a non-browser caller (an MCP server,
a script) uses instead of a passkey/session. Only the SHA-256 hash is
ever stored; the raw key is returned once, at creation, and never again
-- this module can't show it back to you even if asked."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import secrets
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_API_KEY_STORE_PATH = Path("logs/auth_api_keys.json")
_PREFIX_LEN = 8  # shown in the UI so a key is recognizable without revealing it


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ApiKey:
    account_id: str
    key_id: str
    key_hash: str
    prefix: str
    name: str = "API key"
    created_at: str = field(default_factory=_now)
    last_used_at: str | None = None
    revoked: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ApiKey:
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


class ApiKeyStore:
    """Only this class writes `logs/auth_api_keys.json`."""

    def __init__(self, path: Path = DEFAULT_API_KEY_STORE_PATH) -> None:
        self.path = path

    def _load(self) -> list[ApiKey]:
        if not self.path.exists():
            return []
        return [ApiKey.from_dict(d) for d in json.loads(self.path.read_text())]

    def _save(self, records: list[ApiKey]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([r.to_dict() for r in records], indent=2, sort_keys=True))

    def for_account(self, account_id: str) -> list[ApiKey]:
        return [r for r in self._load() if r.account_id == account_id]

    def create(self, account_id: str, name: str | None = None) -> tuple[ApiKey, str]:
        raw_key = "ledger_" + secrets.token_urlsafe(32)
        record = ApiKey(
            account_id=account_id,
            key_id=secrets.token_hex(8),
            key_hash=_hash(raw_key),
            prefix=raw_key[:_PREFIX_LEN],
            name=name or "API key",
        )
        records = self._load()
        records.append(record)
        self._save(records)
        return record, raw_key

    def find_active(self, raw_key: str) -> ApiKey | None:
        """Looks up a caller's bearer key by its hash, e.g. for a
        BearerAuthMiddleware -- not used by the account's own browser
        pages, which carry a session token instead."""
        target_hash = _hash(raw_key)
        records = self._load()
        updated: ApiKey | None = None
        for i, r in enumerate(records):
            if r.key_hash == target_hash and not r.revoked:
                records[i] = updated = ApiKey(**{**r.to_dict(), "last_used_at": _now()})
                break
        if updated is None:
            return None
        self._save(records)
        return updated

    def revoke(self, account_id: str, key_id: str) -> bool:
        records = self._load()
        found = False
        for i, r in enumerate(records):
            if r.account_id == account_id and r.key_id == key_id and not r.revoked:
                records[i] = ApiKey(**{**r.to_dict(), "revoked": True})
                found = True
        if found:
            self._save(records)
        return found
