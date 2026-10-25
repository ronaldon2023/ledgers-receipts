import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "session_start.py"


def run_hook(project: Path, **extra: str) -> str:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    env.pop("RECEIPTS_POLICY", None)
    env.update(extra)
    done = subprocess.run(
        [sys.executable, str(HOOK)], env=env, capture_output=True, text=True, check=True
    )
    return done.stdout


def test_missing_policy_starts_onboarding(tmp_path: Path) -> None:
    out = run_hook(tmp_path)
    assert "/ledgers-receipts:onboarding" in out
    assert "missing" in out


@pytest.mark.parametrize("content", ["{not json", "[]", "null"])
def test_unreadable_policy_is_reported(tmp_path: Path, content: str) -> None:
    (tmp_path / "policy.json").write_text(content)
    out = run_hook(tmp_path)
    assert "isn't a readable policy" in out
    assert "can't approve payments" in out


def test_valid_policy_is_loaded(tmp_path: Path) -> None:
    (tmp_path / "policy.json").write_text(json.dumps({"threshold_cents": 50000}))
    out = run_hook(tmp_path)
    assert out.strip() == "Receipts: payment policy loaded from policy.json."


def test_policy_override_path(tmp_path: Path) -> None:
    other = tmp_path / "elsewhere.json"
    other.write_text("{}")
    assert "loaded from elsewhere.json" in run_hook(tmp_path, RECEIPTS_POLICY=str(other))


def test_empty_override_falls_back_to_project(tmp_path: Path) -> None:
    assert "policy.json is missing" in run_hook(tmp_path, RECEIPTS_POLICY="")


@pytest.mark.parametrize(
    "manifest",
    [".claude-plugin/plugin.json", ".claude-plugin/marketplace.json", "hooks/hooks.json"],
)
def test_plugin_manifests_parse(manifest: str) -> None:
    assert isinstance(json.loads((ROOT / manifest).read_text()), dict)
