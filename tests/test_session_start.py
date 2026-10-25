import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "session_start.py"
ANSWERS = "receipts-onboarding.json"


def run_hook(project: Path, **extra: str) -> str:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    env.pop("RECEIPTS_ONBOARDING", None)
    env.update(extra)
    done = subprocess.run(
        [sys.executable, str(HOOK)], env=env, capture_output=True, text=True, check=True
    )
    return done.stdout


def test_missing_answers_start_onboarding(tmp_path: Path) -> None:
    out = run_hook(tmp_path)
    assert "/ledgers-receipts:onboarding" in out
    assert f"{ANSWERS} is missing" in out


@pytest.mark.parametrize("content", ["{not json", "[]", "null", "[" * 100000])
def test_unreadable_answers_are_reported(tmp_path: Path, content: str) -> None:
    (tmp_path / ANSWERS).write_text(content)
    out = run_hook(tmp_path)
    assert "can't be read" in out
    assert "/ledgers-receipts:onboarding" in out


def test_saved_answers_are_noted(tmp_path: Path) -> None:
    (tmp_path / ANSWERS).write_text(json.dumps({"schema": "receipts-onboarding/0"}))
    out = run_hook(tmp_path)
    assert out.strip() == f"Receipts: onboarding answers on file in {ANSWERS}."


def test_override_path(tmp_path: Path) -> None:
    other = tmp_path / "elsewhere.json"
    other.write_text("{}")
    assert "on file in elsewhere.json" in run_hook(tmp_path, RECEIPTS_ONBOARDING=str(other))


def test_empty_override_falls_back_to_project(tmp_path: Path) -> None:
    assert f"{ANSWERS} is missing" in run_hook(tmp_path, RECEIPTS_ONBOARDING="")


@pytest.mark.parametrize(
    "manifest",
    [".claude-plugin/plugin.json", ".claude-plugin/marketplace.json", "hooks/hooks.json"],
)
def test_plugin_manifests_parse(manifest: str) -> None:
    assert isinstance(json.loads((ROOT / manifest).read_text()), dict)


def test_skill_example_matches_saved_shape() -> None:
    skill = (ROOT / "skills" / "onboarding" / "SKILL.md").read_text()
    example = json.loads(skill.split("```json\n", 1)[1].split("```", 1)[0])
    assert example["schema"] == "receipts-onboarding/0"
    assert example["status"] == "stub"
    assert set(example["integrations"]) == {"bookkeeping", "payments", "email", "other"}
    assert "$500 (Recommended)" in skill
    assert example["payment_rules"]["approval_threshold_cents"] == 50000
    for supplier in example["payment_rules"]["approved_suppliers"]:
        assert len(supplier["account_last4"]) == 4
