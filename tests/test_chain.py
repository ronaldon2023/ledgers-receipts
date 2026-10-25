import json
from pathlib import Path

import pytest

from receipts.chain import append, verify


@pytest.fixture
def log(tmp_path: Path) -> Path:
    path = tmp_path / "chain.jsonl"
    for i in range(5):
        append(
            {"ts": i, "tool": "mcp__bakery-local__save_draft", "response": {"id": f"out_{i}"}}, path
        )
    return path


def lines(path: Path) -> list[str]:
    return path.read_text().splitlines()


def test_fresh_chain_is_intact(log: Path) -> None:
    status = verify(log)
    assert status.ok
    assert status.entries == 5


def test_missing_log_is_empty_and_intact(tmp_path: Path) -> None:
    assert verify(tmp_path / "none.jsonl").entries == 0


def test_edited_line_breaks_chain(log: Path) -> None:
    rows = lines(log)
    record = json.loads(rows[2])
    record["response"]["id"] = "out_99"
    rows[2] = json.dumps(record)
    log.write_text("\n".join(rows) + "\n")
    status = verify(log)
    assert not status.ok
    assert status.line == 3
    assert "edited" in status.error


def test_deleted_line_breaks_chain(log: Path) -> None:
    rows = lines(log)
    del rows[1]
    log.write_text("\n".join(rows) + "\n")
    status = verify(log)
    assert not status.ok
    assert status.line == 2


def test_truncated_log_is_caught_by_head(log: Path) -> None:
    log.write_text("\n".join(lines(log)[:3]) + "\n")
    status = verify(log)
    assert not status.ok
    assert "cut from the end" in status.error


def test_garbage_line_breaks_chain(log: Path) -> None:
    log.write_text(log.read_text() + "not json\n")
    assert not verify(log).ok


def test_append_after_verify_keeps_chain_intact(log: Path) -> None:
    append({"ts": 9, "tool": "GUARD_BLOCK"}, log)
    assert verify(log).entries == 6
