#!/usr/bin/env python3
"""Run a saved HBASE-32 fault plan in a fresh, isolated MiniHBaseCluster."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

from campaign import parse_log, related_after_fault, strict_trace


HERE = Path(__file__).resolve().parent
SPEC = Path(os.environ.get("HBASE32_REPLAY_SPEC", str(HERE / "replay-r003-plan.json")))
JAVA = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin/jcmd")
AGENT_CLASS = HERE.parent / "work/classes/HBase32Agent.class"
HBASE_JAR = Path("/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/hbase-server-2.6.6.jar")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def java_pid(exec_path):
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


def main():
    spec = json.loads(SPEC.read_text())
    if sha256(AGENT_CLASS) != spec["agent_class_sha256"]:
        raise RuntimeError("HBase32Agent bytecode differs from original trial")
    if sha256(HBASE_JAR) != spec["hbase_server_jar_sha256"]:
        raise RuntimeError("HBase server JAR differs from original trial")
    suffix = "replay-" + spec["source_trial"]
    log = HERE / "logs" / (suffix + ".log")
    exec_path = HERE / "logs" / (suffix + ".exec")
    exit_path = HERE / "logs" / (suffix + ".exit")
    if log.exists() or exit_path.exists():
        raise RuntimeError("Replay output already exists; refusing overwrite")
    env = dict(os.environ)
    env["HBASE32_RUN_TIMEOUT"] = str(spec["timeout_seconds"])
    with log.open("w") as output:
        child = subprocess.Popen(["bash", str(HERE / "run.sh"), "run", suffix,
                                  ";".join(spec["plan"])], stdout=output,
                                 stderr=subprocess.STDOUT, env=env)
        started = time.monotonic()
        dumped = set()
        while child.poll() is None:
            elapsed = time.monotonic() - started
            for threshold in (200, 300, 500):
                if elapsed < threshold or threshold in dumped:
                    continue
                dumped.add(threshold)
                pid = java_pid(exec_path)
                if pid:
                    dump = HERE / "logs" / (suffix + f".thread-dump-{threshold}s.txt")
                    with dump.open("w") as stream:
                        subprocess.run([str(JAVA), pid, "Thread.print", "-l"], stdout=stream,
                                       stderr=subprocess.STDOUT, check=False)
            time.sleep(1)
    exit_path.write_text(str(child.returncode) + "\n")
    trace = parse_log(log)
    strict = strict_trace(trace, spec["plan"])
    guards, b7 = related_after_fault(trace, strict)
    cutoff = trace["shutdown_hook_line"]
    pre_shutdown_aborts = sorted({event["server"] for event in trace["rs_aborts"]
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
    result = {"source_trial": spec["source_trial"], "plan": spec["plan"],
              "timeout_seconds": spec["timeout_seconds"],
              "junit": trace["junit"], "exit": child.returncode,
              "elapsed_seconds": trace["elapsed_seconds"],
              "fully_applied": strict, "same_actor_guard": len(guards),
              "same_actor_b7": len(b7),
              "pre_shutdown_aborted_region_servers": pre_shutdown_aborts,
              "all_aborted_region_servers": sorted({event["server"]
                                                      for event in trace["rs_aborts"]}),
              "shutdown_hook_line": cutoff,
              "create_table_procedure_id": create_pid,
              "create_table_child_success_count": completed_children,
              "first_scheduled_server_crash_procedure": first_scp,
              "log_sha256": sha256(log),
              "exec_sha256": sha256(exec_path) if exec_path.exists() else None,
              "agent_class_sha256": sha256(AGENT_CLASS),
              "hbase_server_jar_sha256": sha256(HBASE_JAR)}
    (HERE / "logs" / (suffix + ".summary.json")).write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
