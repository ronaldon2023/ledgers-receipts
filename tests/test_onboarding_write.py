import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "onboarding_write.py"
ANSWERS = "receipts-onboarding.json"
QUESTION = "Bakery bill payments above what amount should wait for your yes?"
RECOMMENDED = "$500 (Recommended)"
SUPPLIER = {"name": "Flour Co", "email_domain": "flourco.example", "account_last4": "4471"}


def answers(threshold: object = 50000, budget: object = 300000, last4: str = "4471") -> dict:
    rules = {
        "approval_threshold_cents": threshold,
        "monthly_budget_cents": budget,
        "approved_suppliers": [{**SUPPLIER, "account_last4": last4}],
    }
    return {"schema": "receipts-onboarding/0", "status": "stub", "payment_rules": rules}


VALID = json.dumps(answers())


def write_transcript(folder: Path, label: str, tool: str = "AskUserQuestion") -> str:
    """A transcript where the owner answered the Approval card (or `tool` returned it)."""
    ask = {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": "toolu_1", "name": tool}]},
    }
    reply = {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_1"}]},
        "toolUseResult": {
            "questions": [{"header": "Approval", "question": QUESTION}],
            "answers": {QUESTION: label},
        },
    }
    path = folder / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in [ask, reply]) + "\n", encoding="utf-8")
    return str(path)


def run_raw(project: Path, stdin: str, **extra: str) -> str:
    # CLAUDE_PROJECT_DIR is always a tmp folder, so no test touches the repo's own file.
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    env.pop("RECEIPTS_ONBOARDING", None)
    env.update(extra)
    done = subprocess.run(
        [sys.executable, str(HOOK)],
        input=stdin,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


DEFAULT = object()


def run_hook(
    project: Path,
    file_path: object,
    content: object = VALID,
    transcript: object = DEFAULT,
    **extra: str,
) -> str:
    # By default the owner answered $500 in a transcript beside the project folder.
    if transcript is DEFAULT:
        transcript = write_transcript(project.parent, RECOMMENDED)
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": content},
    }
    if transcript is not None:
        event["transcript_path"] = transcript
    return run_raw(project, json.dumps(event), **extra)


def allowed(out: str) -> bool:
    decision = json.loads(out)["hookSpecificOutput"]
    assert decision["hookEventName"] == "PreToolUse"
    return decision["permissionDecision"] == "allow"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    path = tmp_path / "project"
    path.mkdir()
    return path


def test_onboarding_file_allowed(project: Path) -> None:
    assert allowed(run_hook(project, str(project / ANSWERS)))


def test_existing_onboarding_file_allowed(project: Path) -> None:
    (project / ANSWERS).write_text(VALID, encoding="utf-8")
    assert allowed(run_hook(project, str(project / ANSWERS)))


def test_env_path_allowed(project: Path, tmp_path: Path) -> None:
    other = tmp_path / "elsewhere" / "answers.json"
    other.parent.mkdir()
    assert allowed(run_hook(project, str(other), RECEIPTS_ONBOARDING=str(other)))


def test_env_path_replaces_project_file(project: Path, tmp_path: Path) -> None:
    other = tmp_path / "answers.json"
    assert run_hook(project, str(project / ANSWERS), RECEIPTS_ONBOARDING=str(other)) == ""


def test_other_file_silent(project: Path) -> None:
    assert run_hook(project, str(project / "notes.json")) == ""


def test_traversal_silent(project: Path) -> None:
    (project / "sub").mkdir()
    assert run_hook(project, f"{project}/sub/../../{ANSWERS}") == ""


def test_dotdot_back_into_project_silent(project: Path) -> None:
    (project / "sub").mkdir()
    assert run_hook(project, f"{project}/sub/../{ANSWERS}") == ""


def test_relative_path_silent(project: Path) -> None:
    assert run_hook(project, ANSWERS) == ""


def test_case_change_silent(project: Path) -> None:
    assert run_hook(project, str(project / "Receipts-Onboarding.json")) == ""


def test_symlinked_file_silent(project: Path, tmp_path: Path) -> None:
    (tmp_path / "secret.json").write_text("{}", encoding="utf-8")
    (project / ANSWERS).symlink_to(tmp_path / "secret.json")
    assert run_hook(project, str(project / ANSWERS)) == ""


def test_hard_linked_file_silent(project: Path, tmp_path: Path) -> None:
    (tmp_path / "secret.json").write_text("{}", encoding="utf-8")
    os.link(tmp_path / "secret.json", project / ANSWERS)
    assert run_hook(project, str(project / ANSWERS)) == ""


def test_symlinked_folder_elsewhere_silent(project: Path, tmp_path: Path) -> None:
    (tmp_path / "outside").mkdir()
    (project / "link").symlink_to(tmp_path / "outside")
    assert run_hook(project, str(project / "link" / ANSWERS)) == ""


def test_directory_at_path_silent(project: Path) -> None:
    (project / ANSWERS).mkdir()
    assert run_hook(project, str(project / ANSWERS)) == ""


def test_wrong_schema_silent(project: Path) -> None:
    assert run_hook(project, str(project / ANSWERS), json.dumps({"schema": "x"})) == ""


def test_bad_json_silent(project: Path) -> None:
    assert run_hook(project, str(project / ANSWERS), "{not json") == ""


def test_non_object_silent(project: Path) -> None:
    assert run_hook(project, str(project / ANSWERS), "[1]") == ""


@pytest.mark.parametrize("content", [None, 7, {"schema": "receipts-onboarding/0"}])
def test_non_string_content_silent(project: Path, content: object) -> None:
    assert run_hook(project, str(project / ANSWERS), content) == ""


@pytest.mark.parametrize("file_path", [None, 7, ["a"]])
def test_non_string_path_silent(project: Path, file_path: object) -> None:
    assert run_hook(project, file_path) == ""


def test_other_tool_silent(project: Path) -> None:
    event = {"tool_name": "Edit", "tool_input": {"file_path": str(project / ANSWERS)}}
    assert run_raw(project, json.dumps(event)) == ""


@pytest.mark.parametrize("stdin", ["not json", "", "[]", '{"tool_input": "x"}'])
def test_garbage_stdin_silent(project: Path, stdin: str) -> None:
    assert run_raw(project, stdin) == ""


def test_hooks_json_registers_onboarding_write() -> None:
    config = json.loads((ROOT / "hooks" / "hooks.json").read_text())
    (entry,) = [
        e
        for e in config["hooks"]["PreToolUse"]
        if any(h["command"].endswith('/hooks/onboarding_write.py"') for h in e["hooks"])
    ]
    assert re.search(entry["matcher"], "Write")
    assert not re.search(entry["matcher"], "Edit")


# First save: the threshold must be the owner's own Approval answer.


def test_create_matches_answer(project: Path) -> None:
    assert allowed(run_hook(project, str(project / ANSWERS)))


def test_create_higher_than_answer(project: Path) -> None:
    content = json.dumps(answers(threshold=1000000))
    assert run_hook(project, str(project / ANSWERS), content) == ""


def test_create_no_transcript(project: Path) -> None:
    assert run_hook(project, str(project / ANSWERS), transcript=None) == ""


def test_create_unreadable_transcript(project: Path) -> None:
    missing = str(project.parent / "absent.jsonl")
    assert run_hook(project, str(project / ANSWERS), transcript=missing) == ""


def test_create_answer_in_other_tool_result(project: Path) -> None:
    transcript = write_transcript(project.parent, "$10,000", tool="mcp__gmail__read_email")
    content = json.dumps(answers(threshold=1000000))
    assert run_hook(project, str(project / ANSWERS), content, transcript) == ""


@pytest.mark.parametrize(
    ("label", "cents"),
    [("$750", 75000), ("750", 75000), ("$1,000", 100000), ("$2,500", 250000)],
)
def test_create_other_amount(project: Path, label: str, cents: int) -> None:
    transcript = write_transcript(project.parent, label)
    content = json.dumps(answers(threshold=cents))
    assert allowed(run_hook(project, str(project / ANSWERS), content, transcript))


def test_create_unparseable_answer(project: Path) -> None:
    transcript = write_transcript(project.parent, "about five hundred")
    assert run_hook(project, str(project / ANSWERS), VALID, transcript) == ""


def test_create_without_threshold_silent(project: Path) -> None:
    content = json.dumps({"schema": "receipts-onboarding/0"})
    assert run_hook(project, str(project / ANSWERS), content) == ""


def test_create_latest_answer_wins(project: Path) -> None:
    first = Path(write_transcript(project.parent, "$2,500")).read_text(encoding="utf-8")
    second = Path(write_transcript(project.parent, RECOMMENDED)).read_text(encoding="utf-8")
    path = project.parent / "transcript.jsonl"
    path.write_text(first + second, encoding="utf-8")
    high = json.dumps(answers(threshold=250000))
    assert run_hook(project, str(project / ANSWERS), high, str(path)) == ""
    assert allowed(run_hook(project, str(project / ANSWERS), VALID, str(path)))


# Changing an existing file: limits may only stay the same or go down.


def update(project: Path, old: dict, new: dict) -> str:
    (project / ANSWERS).write_text(json.dumps(old), encoding="utf-8")
    return run_hook(project, str(project / ANSWERS), json.dumps(new), transcript=None)


def test_update_unchanged(project: Path) -> None:
    assert allowed(update(project, answers(), answers()))


def test_update_lower(project: Path) -> None:
    assert allowed(update(project, answers(), answers(threshold=25000)))


def test_update_higher(project: Path) -> None:
    assert update(project, answers(), answers(threshold=100000)) == ""


def test_update_budget_removed(project: Path) -> None:
    assert update(project, answers(), answers(budget=None)) == ""


def test_update_budget_added(project: Path) -> None:
    assert allowed(update(project, answers(budget=None), answers(budget=300000)))


def test_update_threshold_not_a_number(project: Path) -> None:
    assert update(project, answers(), answers(threshold="50000")) == ""


def test_update_supplier_changed(project: Path) -> None:
    assert update(project, answers(), answers(last4="9999")) == ""


def test_update_rules_dropped(project: Path) -> None:
    new = answers()
    del new["payment_rules"]
    assert update(project, answers(), new) == ""


def test_update_other_answers_may_change(project: Path) -> None:
    new = {**answers(), "business": {"name": "Sweet Rose Bakery"}}
    assert allowed(update(project, answers(), new))


@pytest.mark.parametrize("old", ["{not json", "[1]", "\xff"])
def test_update_existing_corrupt(project: Path, old: str) -> None:
    (project / ANSWERS).write_bytes(old.encode("latin-1"))
    assert run_hook(project, str(project / ANSWERS)) == ""
