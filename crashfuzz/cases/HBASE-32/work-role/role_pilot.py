#!/usr/bin/env python3
"""One original-JUnit role calibration or fault trial per invocation.

This diagnostic ledger is separate from the main, supplemental, and exact
s272 replay ledgers.  An interrupted run is never silently rerun.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from audit_role_run import audit, raw_lines


HERE = Path(__file__).resolve().parent
SPEC = HERE / "role-plan.json"
CHECKPOINT = HERE / "role-pilot-checkpoint.json"
RUNNER = HERE / "run.sh"
BASE_AGENT = HERE / "base-agent.jar"
UPSTREAM_AGENT = HERE / "upstream-agent.jar"
LOCK_AGENT = HERE.parent / "work-upstream/diag-s203/agent.jar"
HBASE_JAR = Path("/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/hbase-server-2.6.6.jar")
HBASE_TEST_JAR = Path("/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/hbase-server-2.6.6-tests.jar")
HBASE_SOURCE = Path("/users/ZhenyuLi/hbase")
NATIVE_JUNIT = HERE.parent / "work/classes/NativeJUnit.class"
JCMD = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin/jcmd")
FAULT_LIMIT = 3
HEALTHY_PASSES_REQUIRED = 2
SOFT_DISK_REVIEW_BYTES = 4 * 1024**3


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            value.update(chunk)
    return value.hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w") as output:
        json.dump(value, output, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp, path)


def spec_preflight() -> dict:
    spec = json.loads(SPEC.read_text())
    plan_hash = hashlib.sha256(json.dumps(spec["plan"], sort_keys=True,
                                          separators=(",", ":")).encode()).hexdigest()
    if plan_hash != spec["plan_sha256"]:
        raise RuntimeError("Frozen role plan differs from its SHA")
    required = {
        RUNNER: "runner_sha256",
        BASE_AGENT: "base_agent_sha256",
        UPSTREAM_AGENT: "upstream_agent_sha256",
        LOCK_AGENT: "lock_agent_sha256",
        HBASE_JAR: "hbase_server_jar_sha256",
        HBASE_TEST_JAR: "hbase_server_test_jar_sha256",
        NATIVE_JUNIT: "native_junit_class_sha256",
    }
    for path, key in required.items():
        if digest(path) != spec[key]:
            raise RuntimeError(f"Frozen input mismatch: {path}")
    source_files = {"base": HERE / "src/HBase32RoleBaseAgent.java",
                    "upstream": HERE / "src/HBase32RoleUpstreamAgent.java",
                    "smoke": HERE / "src/RoleSelectorSmoke.java"}
    for label, path in source_files.items():
        if digest(path) != spec["source_sha256"][label]:
            raise RuntimeError(f"Frozen agent source mismatch: {path}")
    source_commit = subprocess.check_output(
        ["git", "-C", str(HBASE_SOURCE), "rev-parse", "--verify",
         "rel/2.6.6^{commit}"], text=True).strip()
    if source_commit != spec["source_commit"]:
        raise RuntimeError("Original HBase rel/2.6.6 source commit differs")
    if digest(HERE / "audit_role_run.py") != spec["runtime_identity_auditor_sha256"]:
        raise RuntimeError("Role identity auditor differs from frozen spec")
    if digest(Path(__file__)) != spec["pilot_controller_sha256"]:
        raise RuntimeError("Role pilot controller differs from frozen spec")
    return spec


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


def other_java_pids() -> list[str]:
    found = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            args = (proc / "cmdline").read_bytes()
        except (OSError, PermissionError):
            continue
        if args.split(b"\0", 1)[0].endswith(b"/java"):
            found.append(proc.name)
    return found


def tcp_listeners() -> str:
    result = subprocess.run(["ss", "-H", "-lntp"], capture_output=True,
                            text=True, check=True)
    return result.stdout


def healthy_audit(log: Path, exit_code: int, spec: dict) -> dict:
    from audit_role_run import parse_log, fault_events

    trace = parse_log(log)
    meta = []
    master = []
    rpc = []
    for line_no, line in raw_lines(log):
        fields = dict(re.findall(r"([a-z_]+)=([^\s]+)", line))
        if "HBASE32ROLE META_LOCATION " in line:
            meta.append({"line": line_no, **fields})
        elif "HBASE32U MASTER_OPENED_RPC " in line:
            master.append({"line": line_no, **fields})
        elif "HBASE32 IO " in line:
            rpc.append({"line": line_no, **fields})
    f1_prefix = spec["plan"][0].rsplit("~", 1)[0]
    f2_prefix = spec["plan"][1].rsplit("~", 1)[0]
    eligible = []
    for event in master:
        selector = ("MASTER_OPENED_RPC~" + event.get("stable_region", "")
                    + "~replica-" + event.get("replica", "") + "~meta-host")
        if selector != f1_prefix or event.get("role_matched") != "true":
            continue
        latest = next((item for item in reversed(meta)
                       if item["line"] < event["line"]), None)
        if (latest is None or latest.get("state") != "OPEN"
                or latest.get("server") != event.get("server")
                or latest.get("generation") != event.get("meta_host_generation")):
            continue
        actor = (event.get("raw_primary_region"),
                 event.get("raw_secondary_region"), event.get("replica"))
        target = next((item for item in trace["TARGET"]
                       if item["line"] > event["line"]
                       and (item.get("raw_primary_region"),
                           item.get("raw_secondary_region"), item.get("replica")) == actor
                       and item.get("target_ordinal") == "1"), None)
        io = next((item for item in rpc
                   if target is not None and item["line"] > target["line"]
                   and item.get("raw_primary_region") == actor[0]
                   and item.get("context_match") == "true"
                   and item.get("target_ordinal") == "1"
                   and item.get("selector", "").replace("~actor-other~",
                        "~actor-selected~") == f2_prefix), None)
        if target and io:
            eligible.append({"meta": latest, "master": event,
                             "target": target, "client_rpc": io})
    reasons = []
    if exit_code != 0 or trace["junit"] != {"found": 1, "succeeded": 1, "failed": 0}:
        reasons.append("original_junit_not_passed")
    if fault_events(trace):
        reasons.append("unexpected_fault_in_healthy")
    if not eligible:
        reasons.append("no_exact_meta_role_actor_target_rpc_path")
    return {"healthy_gate_passed": not reasons, "reasons": reasons,
            "eligible_actor_count": len(eligible),
            "eligible_actor_examples": eligible[:3],
            "meta_location_events": len(meta), "master_opened_events": len(master),
            "client_rpc_events": len(rpc), "target_invocations": len(trace["TARGET"]),
            "junit": trace["junit"], "elapsed_seconds": trace["elapsed_seconds"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("preflight", "healthy", "fault", "recover"))
    parser.add_argument("--lease-ready", action="store_true",
                        help="operator confirms node0 original-JUnit slot release")
    args = parser.parse_args()
    spec = spec_preflight()
    free = shutil.disk_usage(HERE).free
    if args.action == "preflight":
        print(json.dumps({"inputs_verified": True, "free_bytes": free,
                          "guard_bytes": spec["resource_guard_bytes"],
                          "checkpoint_exists": CHECKPOINT.exists()}))
        return
    if args.action != "recover" and not args.lease_ready:
        raise RuntimeError("Explicit node0 JUnit lease confirmation required")
    if args.action != "recover" and free < spec["resource_guard_bytes"]:
        raise RuntimeError(f"Disk guard: {free} < {spec['resource_guard_bytes']}")
    if (args.action != "recover" and free < SOFT_DISK_REVIEW_BYTES
            and os.environ.get("HBASE32_ROLE_SPACE_REVIEWED") != "1"):
        raise RuntimeError(f"Conservative 4 GiB space review required: free={free}")
    if other_java_pids():
        raise RuntimeError(f"Other node0 Java process present: {other_java_pids()}")
    ports_before = tcp_listeners()
    if re.search(r'users:\(\("java",', ports_before):
        raise RuntimeError("Java TCP listener present before isolated JUnit")
    if CHECKPOINT.exists():
        state = json.loads(CHECKPOINT.read_text())
        if state["plan_sha256"] != spec["plan_sha256"]:
            raise RuntimeError("Checkpoint plan differs")
    else:
        state = {"stage": "distinct_role_aware_diagnostic", "created_utc": now(),
                 "plan_sha256": spec["plan_sha256"], "healthy": None,
                 "healthy_attempts": [],
                 "fault_trials": [], "in_flight": None,
                 "fuzz_budget_admitted": False}
    if args.action == "recover":
        pending = state["in_flight"]
        if pending is None:
            print(json.dumps({"in_flight": None, "recovery_needed": False}))
            return
        suffix = pending["suffix"]
        log = HERE / "logs" / (suffix + ".log")
        exec_file = HERE / "logs" / (suffix + ".exec")
        exit_file = HERE / "logs" / (suffix + ".exit")
        receipt = HERE / "logs" / (suffix + ".receipt.json")
        if receipt.exists():
            result = json.loads(receipt.read_text())
            if (result.get("suffix") != suffix
                    or result.get("plan_sha256") != spec["plan_sha256"]
                    or not log.exists()
                    or result.get("raw_log_sha256") != digest(log)):
                raise RuntimeError("Existing receipt/raw mismatch; manual audit required")
            admit_receipt(state, result)
            print(json.dumps({"suffix": suffix, "promoted_existing_receipt": True}))
            return
        if not log.exists():
            raise RuntimeError("In-flight raw log missing; manual audit required")
        if java_pid(exec_file):
            raise RuntimeError("Original JUnit still running; wait for its natural terminal state")
        if exit_file.exists():
            exit_code = int(exit_file.read_text().strip())
        else:
            tail = log.read_text(errors="replace")[-4000:]
            elapsed = re.search(r"ELAPSED_SECONDS=([\d.]+)", tail)
            nonzero = re.search(r"Command exited with non-zero status (\d+)", tail)
            passed = re.search(r"HBASE32 JUNIT found=1 succeeded=1 failed=0", tail)
            exit_code = (int(nonzero[1]) if elapsed and nonzero else
                         0 if elapsed and passed else None)
        finish(state, spec, suffix, pending["action"], exit_code,
               recovered=True)
        return
    if state["in_flight"] is not None:
        raise RuntimeError("Unsettled in-flight run; inspect raw before resuming")
    if args.action == "healthy":
        if state["healthy"] is not None:
            raise RuntimeError("Healthy run already settled; do not rerun")
        number = len(state["healthy_attempts"]) + 1
        if number > 3:
            raise RuntimeError("Healthy calibration attempt cap reached")
        suffix, base_plan, upstream_plan, timeout = f"healthy-{number:03d}", "", "", 360
    else:
        if state["healthy"] is None or not state["healthy"]["healthy_gate_passed"]:
            raise RuntimeError("Original no-fault cluster calibration has not passed")
        number = len(state["fault_trials"]) + 1
        if number > FAULT_LIMIT:
            raise RuntimeError("Bounded role pilot complete")
        suffix = f"role-f{number:03d}"
        upstream_plan = spec["plan"][0]
        base_plan = spec["plan"][1]
        timeout = 600
    logs = HERE / "logs"
    logs.mkdir(exist_ok=True)
    log = logs / (suffix + ".log")
    exec_file = logs / (suffix + ".exec")
    exit_file = logs / (suffix + ".exit")
    receipt = logs / (suffix + ".receipt.json")
    data_dir = HERE / ("data-" + suffix)
    if any(path.exists() for path in (log, exec_file, exit_file, receipt, data_dir)):
        raise RuntimeError("Existing run evidence; refusing overwrite")
    (logs / (suffix + ".ports-before.txt")).write_text(ports_before)
    state["in_flight"] = {"suffix": suffix, "action": args.action,
                          "started_utc": now(), "preflight_free_bytes": free,
                          "ports_before_sha256": digest(logs / (suffix + ".ports-before.txt"))}
    atomic_json(CHECKPOINT, state)
    env = dict(os.environ, HBASE32_ROLE_TIMEOUT=str(timeout))
    with log.open("w") as output:
        child = subprocess.Popen(["bash", str(RUNNER), "run", suffix,
                                  base_plan, upstream_plan],
                                 stdout=output, stderr=subprocess.STDOUT, env=env)
        started = time.monotonic()
        dumped = set()
        while child.poll() is None:
            elapsed = time.monotonic() - started
            if args.action == "fault":
                for threshold in (130, 200, 300, 500, 607):
                    if elapsed < threshold or threshold in dumped:
                        continue
                    dumped.add(threshold)
                    pid = java_pid(exec_file)
                    if pid:
                        dump = logs / (suffix + f".thread-dump-{threshold}s.txt")
                        with dump.open("w") as stream:
                            subprocess.run([str(JCMD), pid, "Thread.print", "-l"],
                                           stdout=stream, stderr=subprocess.STDOUT,
                                           check=False)
            time.sleep(1)
    (logs / (suffix + ".ports-after.txt")).write_text(tcp_listeners())
    finish(state, spec, suffix, args.action, child.returncode, recovered=False)


def finish(state: dict, spec: dict, suffix: str, action: str,
           exit_code: int | None, recovered: bool) -> None:
    logs = HERE / "logs"
    log = logs / (suffix + ".log")
    exec_file = logs / (suffix + ".exec")
    exit_file = logs / (suffix + ".exit")
    receipt = logs / (suffix + ".receipt.json")
    timeout = 360 if action == "healthy" else 600
    if exit_code is not None and not exit_file.exists():
        temp = exit_file.with_suffix(".exit.tmp")
        with temp.open("w") as output:
            output.write(f"{exit_code}\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, exit_file)
    if exit_code is None:
        result = {"healthy_gate_passed": False, "identity_valid": False,
                  "reasons": ["original_junit_run_interrupted_without_terminal_receipt"],
                  "junit": None, "elapsed_seconds": None}
    else:
        result = (healthy_audit(log, exit_code, spec) if action == "healthy"
                  else audit(log, spec["plan"]))
    result.update({"stage": state["stage"], "suffix": suffix, "action": action,
                   "started_utc": state["in_flight"]["started_utc"],
                   "finished_utc": now(), "exit_code": exit_code,
                   "timeout_seconds": timeout, "plan_sha256": spec["plan_sha256"],
                   "runner_sha256": digest(RUNNER),
                   "pilot_controller_sha256": digest(Path(__file__)),
                   "base_agent_sha256": digest(BASE_AGENT),
                   "upstream_agent_sha256": digest(UPSTREAM_AGENT),
                   "lock_agent_sha256": digest(LOCK_AGENT),
                   "hbase_server_jar_sha256": digest(HBASE_JAR),
                   "hbase_server_test_jar_sha256": digest(HBASE_TEST_JAR),
                   "native_junit_class_sha256": digest(NATIVE_JUNIT),
                   "raw_log_sha256": digest(log),
                   "jacoco_sha256": digest(exec_file) if exec_file.exists() else None,
                   "preflight_free_bytes": state["in_flight"]["preflight_free_bytes"],
                   "ports_before_sha256": state["in_flight"].get("ports_before_sha256"),
                   "ports_after_sha256": (digest(logs / (suffix + ".ports-after.txt"))
                                          if (logs / (suffix + ".ports-after.txt")).exists()
                                          else None),
                   "postflight_free_bytes": shutil.disk_usage(HERE).free,
                   "fuzz_budget_admitted": False,
                   "s272_exact_replay": False,
                   "new_bug": False,
                   "recovered_in_flight": recovered})
    atomic_json(receipt, result)
    admit_receipt(state, result)
    print(json.dumps({"suffix": suffix, "exit_code": exit_code,
                      "healthy_gate_passed": result.get("healthy_gate_passed"),
                      "identity_valid": result.get("identity_valid"),
                      "junit": result.get("junit"),
                      "elapsed_seconds": result.get("elapsed_seconds")}), flush=True)


def admit_receipt(state: dict, result: dict) -> None:
    suffix = result["suffix"]
    if state["in_flight"] is None or state["in_flight"]["suffix"] != suffix:
        raise RuntimeError("Receipt does not match the checkpoint in-flight run")
    known = {trial["suffix"] for trial in state["healthy_attempts"]
             + state["fault_trials"]}
    if suffix in known:
        raise RuntimeError("Receipt would duplicate a settled run")
    if result["action"] == "healthy":
        state["healthy_attempts"].append(result)
        passed = [trial for trial in state["healthy_attempts"]
                  if trial["healthy_gate_passed"]]
        if len(passed) >= HEALTHY_PASSES_REQUIRED:
            state["healthy"] = {"healthy_gate_passed": True,
                                "passed_runs": [trial["suffix"] for trial in passed],
                                "passed_count": len(passed)}
    else:
        state["fault_trials"].append(result)
    state["in_flight"] = None
    atomic_json(CHECKPOINT, state)


if __name__ == "__main__":
    main()
