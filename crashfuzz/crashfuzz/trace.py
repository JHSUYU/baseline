"""Runtime trace files and the small JSON helpers every module shares."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

TRACE_SCHEMA = 3


def rows(path: Path) -> Iterable[dict[str, Any]]:
    """The JSON objects of a jsonl trace.

    A timed-out JVM can be killed while writing its final event, so an
    unterminated last line ends the trace; every earlier event still counts.
    """
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                if not line.endswith("\n"):
                    return
                raise ValueError(f"{path}:{number}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{number}: expected JSON object")
            yield row


def atomic_json(path: Path, value: Any) -> None:
    """Write JSON through a synced temporary file and a rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as stream:
        if path.name == "state.json":
            # A queue can hold tens of thousands of sequences; keep the
            # checkpoint compact, it is rewritten after every trial.
            json.dump(value, stream, sort_keys=True, separators=(",", ":"))
        else:
            json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def fingerprint(value: Any) -> str:
    """A short stable digest of a JSON value."""
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:20]
