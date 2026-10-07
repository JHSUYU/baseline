#!/usr/bin/env python3
"""Durable receipt for one isolated original-JUnit upstream fault trial."""

import os
import hashlib
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
trial_id, plan = sys.argv[1:]
steps = plan.split(";")
base_plan = ";".join(step for step in steps if step.startswith("RPC_FLUSH_REGION~"))
upstream_plan = ";".join(step for step in steps
                         if not step.startswith("RPC_FLUSH_REGION~"))
log = HERE / "logs" / (trial_id + ".log")
receipt = HERE / "logs" / (trial_id + ".exit")
if receipt.exists() or log.exists():
    raise SystemExit("Trial artifacts already exist: " + trial_id)
diag_jar = HERE / "diag-s203" / "agent.jar"
expected_diag_sha = "c4ac78d1f34c4ada2728ebea831dec0505f76aab7f7c1b3ff3b3f98f5d94e4fa"
if hashlib.sha256(diag_jar.read_bytes()).hexdigest() != expected_diag_sha:
    raise SystemExit("Trace-only lock diagnostic agent SHA mismatch")
env = os.environ.copy()
env["HBASE32U_LOCK_DIAG"] = "1"
def java_pid():
    marker = str(HERE / "logs" / (trial_id + ".exec")).encode()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            args = (proc / "cmdline").read_bytes().split(b"\0")
        except (OSError, PermissionError):
            continue
        if args and args[0].endswith(b"/java") and any(marker in arg for arg in args):
            return proc.name
    return None
with log.open("w") as output:
    run = subprocess.Popen(["bash", str(HERE / "run.sh"), "run", trial_id,
                            base_plan, upstream_plan],
                           stdout=output, stderr=subprocess.STDOUT, env=env)
    start = time.monotonic()
    dumped = set()
    while run.poll() is None:
        elapsed = time.monotonic() - start
        for threshold in (130, 200, 300, 350):
            if elapsed < threshold or threshold in dumped:
                continue
            dumped.add(threshold)
            pid = java_pid()
            if pid is not None:
                dump = HERE / "logs" / (trial_id + f".thread-{threshold}s.txt")
                with dump.open("w") as stream:
                    try:
                        subprocess.run(["/usr/lib/jvm/java-8-openjdk-amd64/bin/jcmd",
                                        pid, "Thread.print", "-l"], check=False,
                                       stdout=stream, stderr=subprocess.STDOUT,
                                       timeout=20)
                    except subprocess.TimeoutExpired:
                        stream.write("jcmd timed out after 20 seconds\n")
        time.sleep(1)
temp = receipt.with_suffix(".exit.tmp")
with temp.open("w") as output:
    output.write(str(run.returncode) + "\n")
    output.flush()
    os.fsync(output.fileno())
os.replace(temp, receipt)
