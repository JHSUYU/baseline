#!/usr/bin/env python3
"""Separate trace-only control and exact-plan diagnostic for HBASE-32 s203."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
UPSTREAM = HERE.parent
CASE = UPSTREAM.parent
sys.path.insert(0, str(UPSTREAM))
from campaign import fault_events, parse_log, strict, target_outcome  # noqa: E402


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def pid_for(exec_path: Path) -> str | None:
    marker = str(exec_path).encode()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            args = (proc / "cmdline").read_bytes().split(b"\0")
        except (OSError, PermissionError):
            continue
        if args and args[0].endswith(b"/java") and any(marker in a for a in args):
            return proc.name
    return None


def verify_inputs() -> tuple[dict, dict]:
    spec_path = UPSTREAM / "replay-s203-plan.json"
    source = json.loads(spec_path.read_text())
    overlay = json.loads((HERE / "overlay-spec.json").read_text())
    checks = {
        "source_plan_sha256": spec_path,
        "base_agent_class_sha256": CASE / "work/classes/HBase32Agent.class",
        "upstream_agent_class_sha256": UPSTREAM / "classes/HBase32UpstreamAgent.class",
        "hbase_server_jar_sha256": Path(
            "/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/hbase-server-2.6.6.jar"),
        "diagnostic_source_sha256": HERE / "HBase32LockDiagAgent.java",
        "diagnostic_jar_sha256": HERE / "agent.jar",
        "diagnostic_runner_sha256": HERE / "run_diag.sh",
        "diagnostic_controller_sha256": HERE / "diagnose.py",
    }
    for field, path in checks.items():
        expected = overlay[field]
        if digest(path) != expected:
            raise RuntimeError(f"SHA mismatch: {field} at {path}")
    for field in ("base_agent_class_sha256", "upstream_agent_class_sha256",
                  "hbase_server_jar_sha256"):
        if source[field] != overlay[field]:
            raise RuntimeError(f"Source replay spec differs: {field}")
    if source["source_trial"] != "s203" or source["plan"] != overlay["plan"]:
        raise RuntimeError("Diagnostic plan differs from exact source plan")
    if source["source_plan_sha256"] != overlay["plan_sha256"]:
        raise RuntimeError("Diagnostic plan SHA differs")
    return source, overlay


def run(mode: str) -> None:
    source, overlay = verify_inputs()
    healthy = mode == "healthy"
    if not healthy:
        healthy_summary = HERE / "logs/diag-healthy-s203.summary.json"
        if not healthy_summary.exists():
            raise RuntimeError("Trace-only healthy control must run first")
        control = json.loads(healthy_summary.read_text())
        if (control["exit"] != 0 or
                control["junit"] != {"found": 1, "succeeded": 1, "failed": 0} or
                control["diagnostic_jar_sha256"] != overlay["diagnostic_jar_sha256"] or
                not control["both_classes_woven"]):
            raise RuntimeError("Healthy control did not pass calibration")
    suffix = "diag-healthy-s203" if healthy else "diag-fault-s203"
    log = HERE / "logs" / f"{suffix}.log"
    receipt = HERE / "logs" / f"{suffix}.summary.json"
    exit_file = HERE / "logs" / f"{suffix}.exit"
    exec_file = HERE / "logs" / f"{suffix}.exec"
    data = HERE / f"data-{suffix}"
    if any(p.exists() for p in (log, receipt, exit_file, exec_file, data)):
        raise RuntimeError("Diagnostic output already exists; refusing overwrite")
    stat = os.statvfs(HERE)
    free = stat.f_bavail * stat.f_frsize
    if free < 2_362_232_012:
        raise RuntimeError(f"Node0 free bytes {free} below 2.2 GiB guard")
    base = ";".join(p for p in source["plan"] if p.startswith("RPC_FLUSH_REGION~"))
    upstream = ";".join(p for p in source["plan"] if not p.startswith("RPC_FLUSH_REGION~"))
    if healthy:
        base = upstream = ""
    env = os.environ.copy()
    env["HBASE32_DIAG_TIMEOUT"] = "360" if healthy else "600"
    (HERE / "logs").mkdir(exist_ok=True)
    with log.open("w") as output:
        child = subprocess.Popen(["bash", str(HERE / "run_diag.sh"), "run",
                                  suffix, base, upstream], env=env, stdout=output,
                                 stderr=subprocess.STDOUT)
        started = time.monotonic()
        dumped: set[int] = set()
        while child.poll() is None:
            elapsed = time.monotonic() - started
            for threshold in (() if healthy else (130, 200, 300, 500, 607)):
                if elapsed < threshold or threshold in dumped:
                    continue
                dumped.add(threshold)
                pid = pid_for(exec_file)
                if pid:
                    path = HERE / "logs" / f"{suffix}.thread-{threshold}s.txt"
                    with path.open("w") as stream:
                        subprocess.run(["/usr/lib/jvm/java-8-openjdk-amd64/bin/jcmd",
                                        pid, "Thread.print", "-l"], check=False,
                                       stdout=stream, stderr=subprocess.STDOUT)
            time.sleep(1)
    exit_file.write_text(str(child.returncode) + "\n")
    trace = parse_log(log)
    text = log.read_text(errors="replace")
    lines = text.splitlines()
    markers = [line for line in lines if "HBASE32LOCK " in line]
    values = {
        "mode": mode, "source_trial": "s203", "plan": [] if healthy else source["plan"],
        "plan_sha256": overlay["plan_sha256"],
        "diagnostic_jar_sha256": overlay["diagnostic_jar_sha256"],
        "diagnostic_source_sha256": overlay["diagnostic_source_sha256"],
        "hbase_server_jar_sha256": overlay["hbase_server_jar_sha256"],
        "free_bytes_at_start": free, "timeout_seconds": 360 if healthy else 600,
        "elapsed_seconds": trace["elapsed_seconds"], "exit": child.returncode,
        "junit": trace["junit"], "log_sha256": digest(log),
        "exec_sha256": digest(exec_file) if exec_file.exists() else None,
        "both_classes_woven": all(
            f"HBASE32LOCK PROBE_WOVEN class={name}" in text
            for name in ("org/apache/hadoop/hbase/master/assignment/ServerStateNode",
                         "org/apache/hadoop/hbase/master/assignment/AssignmentManager")),
        "lock_marker_count": len(markers),
        "read_acquire_markers": sum("phase=ACQUIRED" in x and "mode=READ" in x
                                    for x in markers),
        "write_acquire_markers": sum("phase=ACQUIRED" in x and "mode=WRITE" in x
                                     for x in markers),
        "fully_applied": False if healthy else strict(trace, source["plan"]),
        "applied_faults": [] if healthy else fault_events(trace),
        "same_actor_b7": 0 if healthy else len(target_outcome(trace, source["plan"])["b7"]),
        "first_scp": next(({"line": n, "text": line} for n, line in enumerate(lines, 1)
                           if "Scheduled ServerCrashProcedure" in line), None),
        "first_shutdown_hook": next(({"line": n, "text": line} for n, line in enumerate(lines, 1)
                                     if "Shutdown hook starting" in line), None),
        "table2_child_success_count": sum(bool(re.search(
            r"Finished pid=\d+, ppid=20, state=SUCCESS; TransitRegionStateProcedure "
            r"table=testLotsOfRegionRepli2", line)) for line in lines),
        "fuzz_budget_admitted": False,
    }
    receipt.write_text(json.dumps(values, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: values[k] for k in ("mode", "exit", "junit", "fully_applied",
                  "same_actor_b7", "elapsed_seconds", "both_classes_woven",
                  "read_acquire_markers", "write_acquire_markers")}, sort_keys=True))


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("healthy", "fault"):
        raise SystemExit("usage: diagnose.py healthy|fault")
    run(sys.argv[1])
