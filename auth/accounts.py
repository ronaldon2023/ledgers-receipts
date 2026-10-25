"""Owner accounts -- identity + display name, one or more passkeys each
(see auth/webauthn.py). Only this module writes `logs/auth_accounts.json`."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_PATH = Path("logs/auth_accounts.json")


@dataclass(frozen=True, slots=True)
class Account:
    account_id: str
    display_name: str
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Account:
        return cls(**data)


class AccountStore:
    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        self.path = path

    def _load(self) -> list[Account]:
        if not self.path.exists():
            return []
        return [Account.from_dict(d) for d in json.loads(self.path.read_text())]

    def _save(self, accounts: list[Account]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([a.to_dict() for a in accounts], indent=2, sort_keys=True))

    def create(self, display_name: str, account_id: str | None = None) -> Account:
        """Pass `account_id` to match an id already used for a WebAuthn
        registration ceremony started before the account itself was
        persisted (see auth/web.py's signup flow)."""
        account = Account(
            account_id=account_id or f"acct-{uuid.uuid4().hex[:12]}",
            display_name=display_name,
            created_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        accounts = self._load()
        accounts.append(account)
        self._save(accounts)
        return account

    def by_id(self, account_id: str) -> Account | None:
        return next((a for a in self._load() if a.account_id == account_id), None)
