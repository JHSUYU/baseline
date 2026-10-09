#!/usr/bin/env python3
"""One isolated DNR diagnostic to observe the table-state guard I/O."""

import base64
import hashlib
import json
import re
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
HEALTHY = HERE / "logs/healthy2.log"
SUFFIX = "meta-observe"


def choose_plan() -> str:
    for line in HEALTHY.open(errors="replace"):
        if "HBASE32 IO seq=" not in line:
            continue
        match = re.search(r"selector=(\S+) raw_primary_region=(\S+)", line)
        if match is None or "~replica-1~target-1~rpc-1~" not in match[1]:
            continue
        raw = base64.urlsafe_b64decode(match[2] + "=" * (-len(match[2]) % 4))
        if raw.startswith(b"testLotsOfRegionRepli2,"):
            return match[1] + "~DO_NOT_RETRY_IOEXCEPTION"
    raise RuntimeError("No healthy table2 replica-1 target-1 flush RPC")


def main() -> int:
    plan = choose_plan()
    (HERE / "logs/meta-observe.plan").write_text(plan + "\n")
    digest = hashlib.sha256(plan.encode()).hexdigest()
    with (HERE / "logs/meta-observe.log").open("w") as output:
        completed = subprocess.run(["bash", str(HERE / "run.sh"), "run", SUFFIX, plan],
                                   stdout=output, stderr=subprocess.STDOUT, check=False)
    summary = {"status": "diagnostic_not_campaign", "plan_sha256": digest,
               "plan": plan, "exit_code": completed.returncode,
               "raw_log": "work-upstream/logs/meta-observe.log",
               "jacoco_exec": "work-upstream/logs/meta-observe.exec"}
    (HERE / "logs/meta-observe-run.json").write_text(json.dumps(summary, indent=2) + "\n")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
