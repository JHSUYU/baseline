"""Durably collect each terminal remote calibration while its tmux shard runs."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import time

try:
    from .collect import main as collect_main
    from .scheduler import DEFAULT_KEY, ssh_prefix
except ImportError:
    from collect import main as collect_main
    from scheduler import DEFAULT_KEY, ssh_prefix


def session_alive(host: str, key: Path, session: str) -> bool:
    endpoint = {"name": host, "kind": "ssh", "address": f"ZhenyuLi@{host}"}
    result = subprocess.run(ssh_prefix(endpoint, key) +
                            [f"tmux has-session -t {session}"],
                            capture_output=True, text=True, timeout=12)
    if result.returncode not in (0, 1):
        raise RuntimeError(f"{host}: tmux status unavailable: {result.stderr.strip()[:240]}")
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--host", required=True, choices=("node1", "node2"))
    parser.add_argument("--session", required=True)
    parser.add_argument("--cohort", default="")
    parser.add_argument("--dispatch-subdir", default="",
                        help="isolated host-local dispatch state directory")
    parser.add_argument("--ssh-key", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--interval-seconds", type=float, default=60)
    args = parser.parse_args()
    if args.interval_seconds <= 0 or not args.session.replace("-", "").replace("_", "").isalnum():
        parser.error("interval must be positive and session name must be alphanumeric/hyphen/underscore")
    repo = args.repo.resolve()
    while True:
        command = ["--repo", str(repo), "--hosts", args.host, "--ssh-key", str(args.ssh_key)]
        if args.cohort:
            command += ["--cohort", args.cohort]
        if args.dispatch_subdir:
            command += ["--dispatch-subdir", args.dispatch_subdir]
        result = collect_main(command)
        if result:
            return result
        if not session_alive(args.host, args.ssh_key, args.session):
            return collect_main(command)
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
