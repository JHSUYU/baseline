"""Sync and audit terminal remote campaigns from disjoint lane state roots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import time

from .collect import main as collect_main
from .lane_handoff import finalized
from .scheduler import DEFAULT_KEY
from .watch_collect import session_alive


SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def pending_terminal_cases(repo: Path, subdir: str) -> list[str]:
    ready_path = repo / "data/mallory/dispatch" / subdir / "handoff/pins/ready.json"
    try:
        ready = json.loads(ready_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ["ready_manifest_missing_or_invalid"]
    if not isinstance(ready, dict) or not isinstance(ready.get("cases"), list):
        return ["ready_manifest_missing_or_invalid"]
    data_root = repo / "data/mallory"
    return [row["case_id"] for row in ready["cases"]
            if row.get("state") == "ready"
            and not finalized(data_root, row["case_id"])]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("node1", "node2"), required=True)
    parser.add_argument("--lane", action="append", required=True,
                        help="tmux-session:dispatch-subdirectory; repeat for each lane")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--ssh-key", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--ownership", type=Path,
                        default=Path("Mallory/dispatch/shards/ownership.json"),
                        help="pinned effective case ownership for an approved host offload")
    parser.add_argument("--interval-seconds", type=float, default=30)
    args = parser.parse_args()
    lanes = []
    for value in args.lane:
        session, separator, subdir = value.partition(":")
        if not separator or not SAFE.fullmatch(session) or not SAFE.fullmatch(subdir):
            parser.error("each lane needs a safe tmux-session:dispatch-subdirectory")
        lanes.append((session, subdir))
    if len(set(lanes)) != len(lanes) or args.interval_seconds <= 0:
        parser.error("duplicate lane or invalid interval")
    while True:
        errors = []
        for session, subdir in lanes:
            result = collect_main(["--repo", str(args.repo.resolve()), "--hosts", args.host,
                                   "--ssh-key", str(args.ssh_key),
                                   "--ownership", str(args.ownership.resolve()),
                                   "--dispatch-subdir", subdir])
            if result:
                errors.append({"lane": subdir, "exit": result})
        active = [session for session, _ in lanes
                  if session_alive(args.host, args.ssh_key, session)]
        pending = {subdir: pending_terminal_cases(args.repo.resolve(), subdir)
                   for _, subdir in lanes}
        print(json.dumps({"host": args.host, "active_sessions": active,
                          "pending_terminal_cases": pending,
                          "collection_errors": errors}), flush=True)
        if not active and not errors and not any(pending.values()):
            return 0
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
