#!/usr/bin/env python3
"""At most three fresh-fixture repeats of the frozen s203 diagnostic plan."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from diagnose import HERE, UPSTREAM, digest, pid_for, verify_inputs
from campaign import fault_events, parse_log, strict, target_outcome


def main(number: int) -> None:
    if number not in (2, 3, 4):
        raise ValueError("Only three additional diagnostic repeats are authorized")
    source, overlay = verify_inputs()
    control = json.loads((HERE / "logs/diag-healthy-s203.summary.json").read_text())
    if (control["exit"] != 0 or
            control["junit"] != {"found": 1, "succeeded": 1, "failed": 0} or
            control["diagnostic_jar_sha256"] != overlay["diagnostic_jar_sha256"]):
        raise RuntimeError("Healthy control has not passed")
    suffix = f"diag-fault-{number}-s203"
    log = HERE / "logs" / f"{suffix}.log"
    exec_file = HERE / "logs" / f"{suffix}.exec"
    exit_file = HERE / "logs" / f"{suffix}.exit"
    receipt = HERE / "logs" / f"{suffix}.summary.json"
    data = HERE / f"data-{suffix}"
    if any(p.exists() for p in (log, exec_file, exit_file, receipt, data)):
        raise RuntimeError("Output already exists; refusing overwrite")
    stat = os.statvfs(HERE)
    free = stat.f_bavail * stat.f_frsize
    if free < 2_362_232_012:
        raise RuntimeError(f"Node0 free bytes {free} below 2.2 GiB guard")
    base = ";".join(p for p in source["plan"] if p.startswith("RPC_FLUSH_REGION~"))
    upstream = ";".join(p for p in source["plan"] if not p.startswith("RPC_FLUSH_REGION~"))
    env = os.environ.copy()
    env["HBASE32_DIAG_TIMEOUT"] = "600"
    with log.open("w") as output:
        child = subprocess.Popen(["bash", str(HERE / "run_diag.sh"), "run",
                                  suffix, base, upstream], env=env, stdout=output,
                                 stderr=subprocess.STDOUT)
        start = time.monotonic()
        dumped: set[int] = set()
        while child.poll() is None:
            elapsed = time.monotonic() - start
            for threshold in (130, 200, 300, 500, 607):
                if elapsed < threshold or threshold in dumped:
                    continue
                dumped.add(threshold)
                pid = pid_for(exec_file)
                if pid:
                    dump = HERE / "logs" / f"{suffix}.thread-{threshold}s.txt"
                    with dump.open("w") as stream:
                        subprocess.run(["/usr/lib/jvm/java-8-openjdk-amd64/bin/jcmd",
                                        pid, "Thread.print", "-l"], check=False,
                                       stdout=stream, stderr=subprocess.STDOUT)
            time.sleep(1)
    exit_file.write_text(str(child.returncode) + "\n")
    trace = parse_log(log)
    applied = fault_events(trace)
    lines = log.read_text(errors="replace").splitlines()
    selected = next((e for e in applied if e["source"] == "upstream"
                     and e["selector"].startswith("MASTER_OPENED_RPC~")), None)
    meta_open = None
    meta_line = None
    cutoff = selected["line"] if selected is not None else len(lines) + 1
    for line_number, line in enumerate(lines[:cutoff - 1], 1):
        m = re.search(r"Setting hbase:meta replicaId=0 location in ZooKeeper as "
                      r"([^ ]+), state=OPEN$", line)
        if m:
            meta_open, meta_line = m[1], line_number
    first_scp = next(({"line": n, "text": line} for n, line in enumerate(lines, 1)
                      if "Scheduled ServerCrashProcedure" in line), None)
    first_shutdown = next(({"line": n, "text": line} for n, line in enumerate(lines, 1)
                           if "Shutdown hook starting" in line), None)
    result = {
        "source_trial": "s203", "diagnostic_repeat": number,
        "fuzz_budget_admitted": False, "plan": source["plan"],
        "plan_sha256": overlay["plan_sha256"],
        "diagnostic_jar_sha256": overlay["diagnostic_jar_sha256"],
        "diagnostic_runner_sha256": overlay["diagnostic_runner_sha256"],
        "repeat_script_sha256": digest(Path(__file__)),
        "free_bytes_at_start": free, "timeout_seconds": 600,
        "elapsed_seconds": trace["elapsed_seconds"], "exit": child.returncode,
        "junit": trace["junit"], "fully_applied": strict(trace, source["plan"]),
        "applied_faults": applied,
        "same_actor_b7": len(target_outcome(trace, source["plan"])["b7"]),
        "selected_master_report_server": selected["server"] if selected else None,
        "pre_fault_meta_open_server": meta_open,
        "pre_fault_meta_open_line": meta_line,
        "selected_server_carried_meta_at_fault": (
            selected is not None and meta_open == selected["server"]),
        "first_scp": first_scp, "first_shutdown_hook": first_shutdown,
        "table2_child_success_count": sum(bool(re.search(
            r"Finished pid=\d+, ppid=20, state=SUCCESS; TransitRegionStateProcedure "
            r"table=testLotsOfRegionRepli2", line)) for line in lines),
        "diagnostic_woven": all(
                any(f"HBASE32LOCK PROBE_WOVEN class={name}" in line for line in lines)
                for name in ("org/apache/hadoop/hbase/master/assignment/ServerStateNode",
                             "org/apache/hadoop/hbase/master/assignment/AssignmentManager")),
        "log_sha256": digest(log),
        "exec_sha256": digest(exec_file) if exec_file.exists() else None,
    }
    receipt.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: result[k] for k in
                      ("diagnostic_repeat", "exit", "junit", "fully_applied",
                       "same_actor_b7", "selected_server_carried_meta_at_fault",
                       "elapsed_seconds")}, sort_keys=True), flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: repeat.py 2|3|4")
    main(int(sys.argv[1]))
