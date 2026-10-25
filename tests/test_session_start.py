import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "session_start.py"


def run_hook(project: Path) -> str:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    env.pop("RECEIPTS_POLICY", None)
    done = subprocess.run(
        [sys.executable, str(HOOK)], env=env, capture_output=True, text=True, check=True
    )
    return done.stdout


def test_missing_policy_starts_onboarding(tmp_path: Path) -> None:
    out = run_hook(tmp_path)
    assert "/ledgers-receipts:onboarding" in out
    assert "missing" in out


def test_corrupt_policy_is_reported(tmp_path: Path) -> None:
    (tmp_path / "policy.json").write_text("{not json")
    out = run_hook(tmp_path)
    assert "can't be read" in out
    assert "refused" in out


def test_valid_policy_is_loaded(tmp_path: Path) -> None:
    (tmp_path / "policy.json").write_text(json.dumps({"threshold_cents": 50000}))
    out = run_hook(tmp_path)
    assert out.strip() == "Receipts: payment policy loaded from policy.json."
