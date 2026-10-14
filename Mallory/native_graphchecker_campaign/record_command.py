"""Run one original GraphChecker command and retain an executed argv receipt.

The receipt is written only after a successful process exit. It also pins the
generated preparation script that called this helper, so later campaign
preparation can reject edited launch commands before reusing the plan.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def run(script: Path, receipt: Path, stdout: Path, stderr: Path,
        argv: list[str]) -> None:
    if not argv or not script.is_file():
        raise ValueError("original command or preparation script is missing")
    receipt.unlink(missing_ok=True)
    script = script.resolve(strict=True)
    script_sha = _sha(script)
    helper_sha = _sha(Path(__file__))
    with stdout.open("wb") as out, stderr.open("wb") as err:
        subprocess.run(argv, check=True, stdout=out, stderr=err)
    if _sha(script) != script_sha or _sha(Path(__file__)) != helper_sha:
        raise ValueError("original command source changed during execution")
    value = {"schema_version": 1, "argv": argv, "returncode": 0,
             "script": str(script), "script_sha256": script_sha,
             "command_runner_sha256": helper_sha,
             "stdout_sha256": _sha(stdout), "stderr_sha256": _sha(stderr)}
    receipt.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=receipt.parent,
                                     prefix=".original-command-", delete=False) as stream:
        staged = Path(stream.name)
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(staged, receipt)
    finally:
        staged.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--script", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--stdout", required=True, type=Path)
    parser.add_argument("--stderr", required=True, type=Path)
    parser.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.argv or args.argv[0] != "--" or len(args.argv) == 1:
        parser.error("expected -- followed by original GraphChecker argv")
    run(args.script, args.receipt, args.stdout, args.stderr, args.argv[1:])


if __name__ == "__main__":
    main()
