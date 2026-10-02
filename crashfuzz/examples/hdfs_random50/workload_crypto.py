"""Create an encryption zone and request its re-encryption status."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
TEN = HERE.parent / "hdfs_random10"
sys.path.insert(0, str(TEN))
import workload  # noqa: E402


def main() -> None:
    workload.main()
    run_dir = Path(os.environ["ADHOCFUZZ_RUN_DIR"]).resolve()
    rows = []

    def run(name, command, args):
        result = subprocess.run(workload.DOCKER + [
            "exec", "adhocfuzz-hdfs-key-nn", "/opt/hadoop/bin/hdfs",
            command] + args, capture_output=True, text=True, timeout=120)
        rows.append({"name": name, "returncode": result.returncode,
                     "stdout": result.stdout[-2000:],
                     "stderr": result.stderr[-2000:]})
        (run_dir / "crypto-steps.json").write_text(
            json.dumps(rows, indent=2) + "\n")

    run("mkdir-zone", "dfs", ["-mkdir", "-p", "/adhoc-crypto"])
    run("create-zone", "crypto", [
        "-createZone", "-keyName", "adhoc-key", "-path", "/adhoc-crypto"])
    run("touch-encrypted-file", "dfs", ["-touchz", "/adhoc-crypto/file"])
    run("start-reencryption", "crypto", [
        "-reencryptZone", "-start", "-path", "/adhoc-crypto"])
    time.sleep(2)
    run("list-reencryption", "crypto", ["-listReencryptionStatus"])


if __name__ == "__main__":
    main()
