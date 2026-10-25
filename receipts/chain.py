"""Tamper-evident log: one JSON object per line, each holding the previous line's hash.

Editing or deleting any line breaks the chain. Cutting lines off the end leaves a valid
shorter chain, so every append also records the latest hash and count in a small head file
next to the log; verify() compares against it. (Someone who can rewrite both files can
still forge a shorter log. A real deployment would also send the head somewhere off the
machine.)

Usage: python -m receipts.chain [path]   prints whether the chain is intact
"""

import fcntl
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

GENESIS = "0" * 64


def default_path() -> Path:
    root = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    return Path(os.environ.get("RECEIPTS_LOG", Path(root) / "logs" / "chain.jsonl"))


def _canonical(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(entry: dict, prev: str) -> str:
    body = {k: v for k, v in entry.items() if k not in ("prev", "hash")}
    return hashlib.sha256((prev + _canonical(body)).encode()).hexdigest()


def _head_path(path: Path) -> Path:
    return path.with_suffix(".head")


def append(entry: dict, path: Path | None = None) -> dict:
    """Append entry to the log and return it with prev and hash filled in."""
    path = path or default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)  # parallel tool calls must not share a prev hash
        f.seek(0)
        lines = f.read().splitlines()
        prev = json.loads(lines[-1])["hash"] if lines else GENESIS
        record = {**entry, "prev": prev, "hash": _hash(entry, prev)}
        f.write(_canonical(record) + "\n")
        f.flush()
        _head_path(path).write_text(f"{len(lines) + 1} {record['hash']}\n")
    return record


@dataclass
class ChainStatus:
    ok: bool
    entries: int
    head: str
    error: str | None = None
    line: int | None = None  # 1-based line where the chain breaks, matching "log:N" evidence


def verify(path: Path | None = None) -> ChainStatus:
    path = path or default_path()
    if not path.exists():
        return ChainStatus(True, 0, GENESIS)
    prev, count = GENESIS, 0
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            return ChainStatus(False, n - 1, prev, "line is not valid JSON", n)
        if record.get("prev") != prev:
            return ChainStatus(False, n - 1, prev, "a line before this one was removed", n)
        if record.get("hash") != _hash(record, prev):
            return ChainStatus(False, n - 1, prev, "this line was edited", n)
        prev, count = record["hash"], n
    head = _head_path(path)
    if head.exists():
        expected_count, expected_hash = head.read_text().split()
        if int(expected_count) != count or expected_hash != prev:
            return ChainStatus(False, count, prev, "lines were cut from the end of the log")
    return ChainStatus(True, count, prev)


def main() -> None:
    status = verify(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
    where = f" at line {status.line}" if status.line else ""
    print(
        "intact" if status.ok else f"BROKEN{where}: {status.error}", f"({status.entries} entries)"
    )
    sys.exit(0 if status.ok else 1)


if __name__ == "__main__":
    main()
