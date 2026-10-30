"""One worker per node over ssh, all writing one shared results root.

Node ``i`` of ``N`` runs ``worker --shard-index i --shard-count N``: every
``N``-th case of the system, starting at its own. The results root must be
on storage every node mounts at the same path (``/bigtemp`` on liftlab, NFS
on every lift); a case's flock and lease keep two workers from ever running
it at once, and a restarted worker resumes its unfinished cases.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

from . import settings


def worker_command(system: str, results: Path, shard_index: int, shard_count: int,
                   extra: list[str], log: Path) -> str:
    """The detached shell command that starts one node's worker."""
    argv = [sys.executable, "-m", "crashfuzz", "worker", "--system", system,
            "--results", str(results), "--shard-index", str(shard_index),
            "--shard-count", str(shard_count), *extra]
    return (f"mkdir -p {shlex.quote(str(log.parent))} && cd {shlex.quote(str(settings.HOME))} && "
            f"(setsid nohup {shlex.join(argv)} > {shlex.quote(str(log))} 2>&1 < /dev/null &)")


def launch(nodes: list[str], system: str, results: Path, extra: list[str],
           dry_run: bool = False) -> list[str]:
    """Start the workers; return the commands (only print them when dry_run)."""
    commands = []
    for index, node in enumerate(nodes):
        log = results / "logs" / f"worker-{system}-{index}-of-{len(nodes)}.log"
        command = worker_command(system, results, index, len(nodes), extra, log)
        commands.append(f"{node}: {command}")
        if not dry_run:
            subprocess.run(["ssh", "-o", "BatchMode=yes", node, command], check=True)
    return commands
