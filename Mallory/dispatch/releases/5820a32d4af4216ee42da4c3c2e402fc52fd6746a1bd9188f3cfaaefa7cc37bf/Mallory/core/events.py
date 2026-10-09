"""Read a trial trace without inventing missing causal links."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class TraceError(ValueError):
    pass


@dataclass(frozen=True)
class Trace:
    events: tuple[dict[str, Any], ...]
    incomplete_last_line: bool = False


def load_trace(path: Path, *, max_bytes: int = 128 * 1024 * 1024) -> Trace:
    if not path.exists():
        return Trace(())
    if path.stat().st_size > max_bytes:
        raise TraceError(f"trace exceeds {max_bytes} bytes: {path}")
    result: list[dict[str, Any]] = []
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    incomplete = False
    for index, line in enumerate(lines, 1):
        if not line.strip():
            continue
        if not line.endswith(b"\n") and index == len(lines):
            incomplete = True
            break
        try:
            event = json.loads(line)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise TraceError(f"{path}:{index}: {exc}") from exc
        if not isinstance(event, dict):
            raise TraceError(f"{path}:{index}: expected object")
        if "type" not in event or not isinstance(event["type"], str):
            raise TraceError(f"{path}:{index}: missing type")
        event.setdefault("seq", index)
        result.append(event)
    return Trace(tuple(result), incomplete)


def event_address(event: dict[str, Any]) -> str | None:
    """A per-run occurrence address, including logical node and restart epoch."""
    value = event.get("occurrence")
    if not isinstance(value, str) or not value:
        return None
    node = event.get("node")
    epoch = event.get("epoch")
    if (not isinstance(node, str) or node in ("", "unknown", "null", "None")
            or epoch is None):
        return None
    return json.dumps([str(node), str(epoch), value], separators=(",", ":"))


def event_seq(event: dict[str, Any]) -> int:
    value = event.get("seq")
    return value if isinstance(value, int) else -1
