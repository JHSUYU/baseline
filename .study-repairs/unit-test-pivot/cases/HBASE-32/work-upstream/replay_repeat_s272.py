#!/usr/bin/env python3
"""Run one bounded same-plan s272 repeat in a fresh unchanged HBase MiniCluster."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

from campaign import fault_events, parse_log, raw_log_sha256, strict, target_outcome


HERE = Path(__file__).resolve().parent
SPEC = Path(os.environ["HBASE32U_REPLAY_SPEC"])
JAVA = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin/jcmd")
BASE_AGENT = HERE.parent / "work/classes/HBase32Agent.class"
UPSTREAM_AGENT = HERE / "classes/HBase32UpstreamAgent.class"
HBASE_JAR = Path("/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/hbase-server-2.6.6.jar")
LOCK_DIAG_AGENT = HERE / "diag-s203/agent.jar"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def java_pid(exec_path: Path) -> str | None:
    marker = str(exec_path).encode()
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


def main() -> None:
    spec = json.loads(SPEC.read_text())
    for path, field in ((BASE_AGENT, "base_agent_class_sha256"),
                        (UPSTREAM_AGENT, "upstream_agent_class_sha256"),
                        (HBASE_JAR, "hbase_server_jar_sha256")):
        if sha256(path) != spec[field]:
            raise RuntimeError(f"Replay binary differs at {path}")
    if "diagnostic_agent_jar_sha256" in spec:
        if sha256(LOCK_DIAG_AGENT) != spec["diagnostic_agent_jar_sha256"]:
            raise RuntimeError("Trace-only diagnostic overlay differs")
    if "replay_runner_sha256" in spec and sha256(Path(__file__)) != spec["replay_runner_sha256"]:
        raise RuntimeError("Replay runner differs")
    source_log = HERE / "logs" / (spec["source_trial"] + ".log.gz")
    source_exec = HERE / "logs" / (spec["source_trial"] + ".exec")
    if (sha256(source_log) != spec["source_compressed_log_sha256"] or
            raw_log_sha256(source_log) != spec["source_raw_log_sha256"] or
            sha256(source_exec) != spec["source_jacoco_sha256"]):
        raise RuntimeError("Original raw trial differs from replay specification")
    suffix = spec["replay_suffix"]
    if (spec["source_trial"] != "s272" or
            not re.fullmatch(r"replay-s272-[2-6]", suffix)):
        raise RuntimeError("Only bounded s272 repeats 2..6 are allowed")
    free = os.statvfs(HERE).f_bavail * os.statvfs(HERE).f_frsize
    if free < 2_362_232_012:
        raise RuntimeError("Insufficient node0 space for another original JUnit")
    log = HERE / "logs" / (suffix + ".log")
    exec_path = HERE / "logs" / (suffix + ".exec")
    exit_path = HERE / "logs" / (suffix + ".exit")
    summary_path = HERE / "logs" / (suffix + ".summary.json")
    data_dir = HERE / ("data-" + suffix)
    if any(path.exists() for path in (log, exec_path, exit_path, summary_path, data_dir)):
        raise RuntimeError("Replay output already exists; refusing overwrite")
    base_plan = ";".join(step for step in spec["plan"]
                         if step.startswith("RPC_FLUSH_REGION~"))
    upstream_plan = ";".join(step for step in spec["plan"]
                             if not step.startswith("RPC_FLUSH_REGION~"))
    if not base_plan or not upstream_plan:
        raise RuntimeError("Expected one mixed upstream/client RPC plan")
    env = dict(os.environ)
    env["HBASE32_UPSTREAM_TIMEOUT"] = str(spec["timeout_seconds"])
    if "diagnostic_agent_jar_sha256" in spec:
        env["HBASE32U_LOCK_DIAG"] = "1"
    with log.open("w") as output:
        child = subprocess.Popen(["bash", str(HERE / "run.sh"), "run", suffix,
                                  base_plan, upstream_plan], stdout=output,
                                 stderr=subprocess.STDOUT, env=env)
        started = time.monotonic()
        dumped: set[int] = set()
        while child.poll() is None:
            elapsed = time.monotonic() - started
            for threshold in (130, 200, 300, 500, 607):
                if elapsed < threshold or threshold in dumped:
                    continue
                dumped.add(threshold)
                pid = java_pid(exec_path)
                if pid:
                    dump = HERE / "logs" / (suffix + f".thread-dump-{threshold}s.txt")
                    with dump.open("w") as stream:
                        subprocess.run([str(JAVA), pid, "Thread.print", "-l"],
                                       stdout=stream, stderr=subprocess.STDOUT,
                                       check=False)
            time.sleep(1)
    exit_path.write_text(str(child.returncode) + "\n")
    trace = parse_log(log)
    applied = fault_events(trace)
    matched = strict(trace, spec["plan"])
    reached = target_outcome(trace, spec["plan"])
    cutoff = trace["shutdown_hook_line"]
    aborts = sorted({event["server"] for event in trace["RS_ABORT"]
                     if cutoff is None or event["line"] < cutoff})
    lines = log.read_text(errors="replace").splitlines()
    create_pid = next((match.group(1) for line in lines
                       if (match := re.search(
                           r"CreateTableProcedure: pid=(\d+).*"
                           r"CreateTableProcedure table=testLotsOfRegionRepli2 "
                           r"execute state=CREATE_TABLE_PRE_OPERATION", line))), None)
    completed_children = 0 if create_pid is None else sum(
        bool(re.search(r"Finished pid=\d+, ppid=" + re.escape(create_pid)
                       + r", state=SUCCESS; TransitRegionStateProcedure "
                       + r"table=testLotsOfRegionRepli2", line)) for line in lines)
    first_scp = next(({"line": index + 1, "message": line}
                      for index, line in enumerate(lines)
                      if "Scheduled ServerCrashProcedure" in line), None)
    selected = next((event for event in applied if event["source"] == "upstream"
                     and event["selector"].startswith("MASTER_OPENED_RPC~")), None)
    meta_host = None
    meta_line = None
    for number, line in enumerate(lines[:selected["line"] - 1] if selected else [], 1):
        match = re.search(r"Setting hbase:meta replicaId=0 location in ZooKeeper as "
                          r"([^ ]+), state=OPEN$", line)
        if match:
            meta_host, meta_line = match[1], number
    result = {
        "source_trial": spec["source_trial"], "plan": spec["plan"],
        "timeout_seconds": spec["timeout_seconds"], "exit": child.returncode,
        "elapsed_seconds": trace["elapsed_seconds"], "junit": trace["junit"],
        "fully_applied": matched, "applied_faults": applied,
        "same_actor_guard": len(reached["guard"]),
        "same_actor_b7": len(reached["b7"]),
        "pre_shutdown_aborted_region_servers": aborts,
        "create_table_procedure_id": create_pid,
        "create_table_child_success_count": completed_children,
        "first_scheduled_server_crash_procedure": first_scp,
        "selected_master_report_server": selected["server"] if selected else None,
        "pre_fault_meta_open_server": meta_host,
        "pre_fault_meta_open_line": meta_line,
        "selected_server_carried_meta_at_fault": bool(
            selected and meta_host == selected["server"]),
        "free_bytes_at_start": free,
        "replay_suffix": suffix,
        "log_sha256": sha256(log),
        "exec_sha256": sha256(exec_path) if exec_path.exists() else None,
        "base_agent_class_sha256": sha256(BASE_AGENT),
        "upstream_agent_class_sha256": sha256(UPSTREAM_AGENT),
        "hbase_server_jar_sha256": sha256(HBASE_JAR),
        "diagnostic_agent_jar_sha256": (
            sha256(LOCK_DIAG_AGENT) if "diagnostic_agent_jar_sha256" in spec else None),
        "fuzz_budget_admitted": False,
    }
    summary_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
