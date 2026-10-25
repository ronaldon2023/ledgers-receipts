import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from bakery.seed import VENDORS, seed

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "onboarding" / "read_bakery.py"


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "bakery.db"
    seed(path)
    return path


def run(project: Path, **extra: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    env.pop("BAKERY_DB", None)
    env.update(extra)
    return subprocess.run(
        [sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True, check=False
    )


def test_vendors_show_last4_only(db: Path) -> None:
    done = run(db.parent, BAKERY_DB=str(db))
    assert done.returncode == 0
    out = json.loads(done.stdout)
    assert out["vendors"] == [
        {"name": name, "email_domain": email.split("@")[1], "account_last4": account[-4:]}
        for _, name, email, account in sorted(VENDORS, key=lambda v: v[1])
    ]
    # The cents fields are 5+ digit runs by design, so check the vendors part and the raw text.
    assert not re.search(r"\d{5,}", json.dumps(out["vendors"]))
    for *_, account in VENDORS:
        assert account not in done.stdout


def test_policies_come_from_db(db: Path) -> None:
    out = json.loads(run(db.parent, BAKERY_DB=str(db)).stdout)
    assert out["approval_threshold_cents"] == 50000
    assert out["monthly_budget_cents"] == 300000


def test_relative_bakery_db_resolves_against_project_dir(db: Path) -> None:
    out = json.loads(run(db.parent, BAKERY_DB="bakery.db").stdout)
    assert out["approval_threshold_cents"] == 50000


def test_default_path_is_project_dir(db: Path) -> None:
    out = json.loads(run(db.parent).stdout)
    assert out["monthly_budget_cents"] == 300000


def test_missing_db_reports_error(tmp_path: Path) -> None:
    done = run(tmp_path, BAKERY_DB=str(tmp_path / "nope.db"))
    assert done.returncode == 0
    assert set(json.loads(done.stdout)) == {"error"}
    assert not (tmp_path / "nope.db").exists()


def test_db_is_not_modified(db: Path) -> None:
    before = (hashlib.sha256(db.read_bytes()).hexdigest(), db.stat().st_mtime_ns)
    run(db.parent, BAKERY_DB=str(db))
    assert (hashlib.sha256(db.read_bytes()).hexdigest(), db.stat().st_mtime_ns) == before
