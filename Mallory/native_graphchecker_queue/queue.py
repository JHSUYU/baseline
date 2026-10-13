"""Run two independent native campaigns per owner host with durable receipts.

Only the original native campaign is called. The existing one-case dispatcher
remains useful for inspection, but its host-wide lock cannot schedule two cases.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from Mallory.native_graphchecker_campaign.campaign import run_campaign
from Mallory.native_graphchecker_dispatch.checklist import (
    DEFAULT_INVENTORY, DEFAULT_OWNERSHIP, inspect_case, load_inventory,
    load_ownership, load_reviews,
)

HOSTS = ("node0", "node1", "node2")
MAX_SLOTS = 2
TERMINAL = {"tested_candidate", "tested_no_target_throw",
            "tested_inconclusive", "native_blocked"}
PORT_CONFLICT = re.compile(rb"Address already in use|EADDRINUSE|Port already in use",
                           re.IGNORECASE)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def obj(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=".native-queue-", delete=False) as out:
        temporary = Path(out.name)
        json.dump(value, out, sort_keys=True, indent=2)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def physical_host(host: str) -> None:
    if host not in HOSTS or socket.gethostname().split(".")[0] != host:
        raise ValueError("native queue must run on its physical owner host")


def _same_or_write(path: Path, receipt: dict[str, Any]) -> None:
    if path.exists():
        if obj(path) != receipt:
            raise ValueError(f"native completion receipt changed: {path}")
    else:
        atomic(path, receipt)


def port_conflict_logs(root: Path) -> list[str]:
    """Conservatively reject JUnit trials with an actual bind collision."""
    hits = []
    for path in sorted((root / "trials").glob("r*/[a-z]*err.log")) + sorted(
            (root / "trials").glob("r*/stdout.log")):
        with path.open("rb") as stream:
            previous = b""
            while block := stream.read(1 << 20):
                if PORT_CONFLICT.search(previous + block):
                    hits.append(str(path.resolve()))
                    break
                previous = block[-64:]
    return hits


def completion(item: dict, row: dict, config_file: Path, state_root: Path,
               queue_root: Path) -> dict[str, Any]:
    """Publish only a terminal result already audited by native inspect_case."""
    if row["terminal_disposition"] not in TERMINAL:
        raise ValueError("native case has no audited terminal disposition")
    case_id = item["case_id"]
    conflicts = port_conflict_logs(state_root / case_id)
    if conflicts:
        marker = queue_root / "invalid-overlap" / f"{case_id}.json"
        atomic(marker, {"schema_version": 1, "case_id": case_id,
                        "reason": "JUnit listener port collision",
                        "log_paths": conflicts})
        raise ValueError(f"native JUnit port collision requires review: {marker}")
    if (queue_root / "invalid-overlap" / f"{case_id}.json").exists():
        raise ValueError("prior native port collision requires review")
    summary = state_root / case_id / "summary.json"
    receipt = {
        "schema_version": 1, "method": "original_native_graphchecker_campaign",
        "case_id": case_id, "system": item["system"],
        "source_path": item["target"]["source_path"],
        "source_line": item["target"]["source_line"],
        "target_site": item["target"]["site_id"],
        "target_exception": item["target"].get("target_exception"),
        "original_junit": item["workload"].get("selected_selector"),
        "terminal_disposition": row["terminal_disposition"],
        "native_tested_complete": row["native_tested_complete"],
        "bug_candidate": row["terminal_disposition"] == "tested_candidate",
        "fault_trials": row["fault_trials"],
        "strict_fault_trials": row["strict_fault_trials"],
        "target_retained_fault_trials": row["target_retained_fault_trials"],
        "target_throw_trials": row["target_throw_trials"],
        "candidate_trials": row["candidate_trials"],
        "elapsed_seconds": row["elapsed_seconds"],
        "config_path": str(config_file.resolve()),
        "config_sha256": sha(config_file),
        "summary_path": str(summary.resolve()),
        "summary_sha256": sha(summary),
    }
    _same_or_write(queue_root / "completions" / f"{case_id}.json", receipt)
    return receipt


def _contains_trial_dir(config: dict[str, Any]) -> bool:
    args = config.get("runner", {}).get("jvm_args", [])
    data_keys = ("build.test.dir", "test.build.data.basedirectory",
                 "hadoop.tmp.dir", "solr.solr.home", "solr.data.dir",
                 "test.data.dir", "derby.system.home")
    for arg in args:
        for key in ("java.io.tmpdir", *data_keys):
            if arg.startswith(f"-D{key}=") and arg != f"-D{key}={{trial_workdir}}":
                return False
    return (any(arg == "-Djava.io.tmpdir={trial_workdir}" for arg in args)
            and any(f"-D{key}={{trial_workdir}}" in args for key in data_keys))


def validate_isolation(profile: dict[str, Any], system: str, case_id: str,
                       config: dict[str, Any], ownership: dict[str, str],
                       host: str) -> dict[str, Any]:
    """Require a documented, pinned port policy and per-trial JUnit dirs.

    Ephemeral policy requires reviewed evidence that every service listener
    binds port zero. Assigned policy requires unique per-case ranges and the
    exact JVM settings that select them. These are explicit launch contracts;
    the queue cannot infer a workload's bind behavior from JUnit success.
    """
    if profile.get("schema_version") != 1:
        raise ValueError("invalid isolation profile schema")
    system_policy = profile.get("systems", {}).get(system)
    if not isinstance(system_policy, dict):
        raise ValueError(f"missing port isolation policy for {system}")
    ports = system_policy.get("ports")
    if not isinstance(ports, dict) or ports.get("mode") not in ("ephemeral", "assigned"):
        raise ValueError("port policy must be ephemeral or assigned")
    evidence = ports.get("evidence")
    if not isinstance(evidence, dict) or not evidence:
        raise ValueError("port policy lacks pinned source evidence")
    for name, expected in evidence.items():
        path = Path(name)
        if (not path.is_absolute() or not path.is_file() or path.is_symlink() or
                not isinstance(expected, str) or sha(path) != expected):
            raise ValueError(f"port isolation evidence changed: {name}")
    if not _contains_trial_dir(config):
        raise ValueError("JUnit needs isolated tmpdir and cluster data directory")
    args = config["runner"]["jvm_args"]
    required = system_policy.get("required_jvm_args", [])
    if (not isinstance(required, list) or
            not all(isinstance(arg, str) and arg in args for arg in required)):
        raise ValueError("missing required JUnit isolation JVM argument")
    if ports["mode"] == "ephemeral":
        receipt_path = Path(ports.get("receipt", ""))
        if (not receipt_path.is_absolute() or not receipt_path.is_file() or
                str(receipt_path) not in evidence):
            raise ValueError("ephemeral ports require a pinned dynamic-port receipt")
        receipt = obj(receipt_path)
        if (receipt.get("schema_version") != 1 or
                receipt.get("system") != system or
                receipt.get("all_listeners_bind_port_zero") is not True):
            raise ValueError("dynamic-port receipt does not attest this system")
        return {"mode": "ephemeral", "evidence": evidence}
    assignments = ports.get("cases")
    if not isinstance(assignments, dict) or case_id not in assignments:
        raise ValueError(f"missing assigned port range for {case_id}")
    used: list[tuple[int, int, str]] = []
    for other_id, assignment in assignments.items():
        if other_id not in ownership or ownership[other_id] != host:
            continue
        if not isinstance(assignment, dict):
            raise ValueError("invalid port assignment")
        start, count = assignment.get("start"), assignment.get("count")
        if (not isinstance(start, int) or isinstance(start, bool) or
                not isinstance(count, int) or isinstance(count, bool) or
                start < 1024 or count <= 0 or start + count > 65536):
            raise ValueError("invalid assigned port range")
        for lower, upper, previous in used:
            if start < upper and lower < start + count:
                raise ValueError(f"port ranges overlap: {previous}, {other_id}")
        used.append((start, start + count, other_id))
    mine = assignments[case_id]
    required = mine.get("required_jvm_args")
    if (not isinstance(required, list) or not required or
            not all(isinstance(arg, str) and arg in args for arg in required)):
        raise ValueError("assigned ports are not selected by pinned JUnit config")
    return {"mode": "assigned", "start": mine["start"],
            "count": mine["count"], "evidence": evidence}


def _resources(state_root: Path, scratch_root: Path,
               min_memory_gib: float, min_state_gib: float,
               min_scratch_gib: float) -> None:
    available_kib = 0
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            available_kib = int(line.split()[1])
            break
    if available_kib < min_memory_gib * 1024 ** 2:
        raise RuntimeError("native queue memory floor not met")
    if shutil.disk_usage(state_root).free < min_state_gib * 1024 ** 3:
        raise RuntimeError("native queue durable state floor not met")
    if shutil.disk_usage(scratch_root).free < min_scratch_gib * 1024 ** 3:
        raise RuntimeError("native queue scratch floor not met")


def pilot_receipt(path: Path, inventory: Path, ownership_file: Path,
                  config_root: Path, state_root: Path, cases: list[dict],
                  owners: dict[str, str], isolation_file: Path) -> dict[str, Any]:
    receipt = obj(path)
    case_id = receipt.get("case_id")
    item = next((item for item in cases if item["case_id"] == case_id), None)
    if (receipt.get("schema_version") != 1 or receipt.get("passed") is not True or
            item is None or receipt.get("host") != owners.get(case_id) or
            receipt.get("inventory_sha256") != sha(inventory) or
            receipt.get("ownership_sha256") != sha(ownership_file) or
            receipt.get("isolation_sha256") != sha(isolation_file)):
        raise ValueError("native pilot receipt identity changed")
    row = inspect_case(item, owners[case_id], config_root, state_root)
    if row["native_tested_complete"] is not True:
        raise ValueError("native pilot is not an audited completed fuzz check")
    if ((state_root / ".native-queue" / "invalid-overlap" /
         f"{case_id}.json").exists() or port_conflict_logs(state_root / case_id)):
        raise ValueError("native pilot contains a JUnit port collision")
    config_file = config_root / f"{case_id}.json"
    summary = state_root / case_id / "summary.json"
    if (receipt.get("config_sha256") != sha(config_file) or
            receipt.get("summary_sha256") != sha(summary)):
        raise ValueError("native pilot evidence changed")
    return receipt


def run_worker(*, host: str, slot: int, slots: int, inventory: Path,
               ownership_file: Path, config_root: Path, state_root: Path,
               scratch_root: Path, isolation_file: Path,
               reviews: Path | None = None, only_case: str | None = None,
               min_memory_gib: float = 12, min_state_gib: float = 2,
               min_scratch_gib: float = 4,
               runner: Callable[[Path, Path], dict] = run_campaign) -> dict[str, Any]:
    physical_host(host)
    if not 1 <= slots <= MAX_SLOTS or not 0 <= slot < slots:
        raise ValueError("native queue supports one or two slots per host")
    cases, by_id = load_inventory(inventory)
    owners = load_ownership(ownership_file, set(by_id))
    reviewed = load_reviews(reviews, set(by_id))
    if only_case is not None and (only_case not in by_id or owners[only_case] != host):
        raise ValueError("pilot case is not assigned to this host")
    profile = obj(isolation_file)
    state_root.mkdir(parents=True, exist_ok=True)
    scratch_root.mkdir(parents=True, exist_ok=True)
    queue_root = state_root / ".native-queue"
    slot_root = queue_root / host / f"slot-{slot}"
    slot_root.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    # The older run-next takes an exclusive host lock. Shared leases let our
    # two slots coexist but prevent overlap with that single-case dispatcher.
    with (state_root / f".host-{host}.lock").open("a+") as host_lease, (
            slot_root / ".slot.lock").open("a+") as lane:
        fcntl.flock(host_lease, fcntl.LOCK_SH | fcntl.LOCK_NB)
        fcntl.flock(lane, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for item in cases:
            case_id = item["case_id"]
            if owners[case_id] != host or (only_case and case_id != only_case):
                continue
            root = state_root / case_id
            row = inspect_case(item, host, config_root, state_root,
                               reviewed.get(case_id))
            if row["terminal_disposition"] in TERMINAL:
                validate_isolation(profile, item["system"], case_id,
                                   obj(config_root / f"{case_id}.json"),
                                   owners, host)
                completion(item, row, config_root / f"{case_id}.json",
                           state_root, queue_root)
                continue
            if row["terminal_disposition"] not in ("ready", "resumable"):
                continue
            root.mkdir(parents=True, exist_ok=True)
            with (root / ".dispatch.lock").open("a+") as case_lock:
                try:
                    fcntl.flock(case_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                row = inspect_case(item, host, config_root, state_root,
                                   reviewed.get(case_id))
                if row["terminal_disposition"] not in ("ready", "resumable"):
                    continue
                config_file = config_root / f"{case_id}.json"
                isolation = validate_isolation(profile, item["system"], case_id,
                                               obj(config_file), owners, host)
                _resources(state_root, scratch_root, min_memory_gib,
                           min_state_gib, min_scratch_gib)
                scratch = scratch_root / case_id
                if scratch.is_symlink():
                    raise ValueError("case scratch path is a symlink")
                scratch.mkdir(exist_ok=True)
                attempt_file = (queue_root / "attempts" / case_id /
                                f"{time.time_ns()}-{os.getpid()}.json")
                attempt = {"schema_version": 1, "case_id": case_id,
                           "host": host, "slot": slot, "pid": os.getpid(),
                           "config_sha256": sha(config_file),
                           "isolation_sha256": sha(isolation_file),
                           "port_policy": isolation,
                           "scratch_path": str(scratch.resolve()),
                           "state_path": str(root.resolve()),
                           "started_at": time.time(), "status": "running"}
                atomic(attempt_file, attempt)
                previous_tmpdir = os.environ.get("TMPDIR")
                os.environ["TMPDIR"] = str(scratch.resolve())
                try:
                    runner(config_file, root)
                    after = inspect_case(item, host, config_root, state_root,
                                         reviewed.get(case_id))
                    if sha(isolation_file) != attempt["isolation_sha256"]:
                        raise ValueError("native isolation profile changed during campaign")
                    validate_isolation(profile, item["system"], case_id,
                                       obj(config_file), owners, host)
                    if after["terminal_disposition"] not in TERMINAL:
                        raise RuntimeError("native campaign returned without audited terminal result")
                    result = completion(item, after, config_file, state_root,
                                        queue_root)
                    attempt.update(status="complete", ended_at=time.time(),
                                   completion_path=str(queue_root / "completions" /
                                                       f"{case_id}.json"))
                    atomic(attempt_file, attempt)
                    results.append(result)
                except Exception as failure:
                    attempt.update(status="failed", ended_at=time.time(),
                                   error=f"{type(failure).__name__}: {failure}")
                    atomic(attempt_file, attempt)
                    raise
                finally:
                    if previous_tmpdir is None:
                        os.environ.pop("TMPDIR", None)
                    else:
                        os.environ["TMPDIR"] = previous_tmpdir
    return {"host": host, "slot": slot, "completed": len(results),
            "cases": [row["case_id"] for row in results]}


def run_host(*, host: str, slots: int, pilot: Path, inventory: Path,
             ownership_file: Path, config_root: Path, state_root: Path,
             scratch_root: Path, isolation_file: Path,
             reviews: Path | None = None,
             min_memory_gib: float = 12, min_state_gib: float = 2,
             min_scratch_gib: float = 4) -> list[int]:
    physical_host(host)
    if not 1 <= slots <= MAX_SLOTS:
        raise ValueError("native queue supports at most two slots per host")
    cases, by_id = load_inventory(inventory)
    owners = load_ownership(ownership_file, set(by_id))
    pilot_receipt(pilot, inventory, ownership_file, config_root, state_root,
                  cases, owners, isolation_file)
    profile = obj(isolation_file)
    for item in cases:
        case_id = item["case_id"]
        if owners[case_id] != host:
            continue
        row = inspect_case(item, host, config_root, state_root)
        if row["terminal_disposition"] not in ("ready", "resumable"):
            continue
        validate_isolation(profile, item["system"], case_id,
                           obj(config_root / f"{case_id}.json"), owners, host)
    # Each worker owns a separate process and slot lock. Case locks arbitrate
    # selection, including after a controller crash or a second invocation.
    processes = []
    for slot in range(slots):
        argv = [sys.executable, "-m", "Mallory.native_graphchecker_queue",
                "worker", "--host", host, "--slot", str(slot),
                "--slots", str(slots), "--inventory", str(inventory),
                "--ownership", str(ownership_file),
                "--config-root", str(config_root), "--state-root", str(state_root),
                "--scratch-root", str(scratch_root),
                "--isolation", str(isolation_file),
                "--min-memory-gib", str(min_memory_gib),
                "--min-state-gib", str(min_state_gib),
                "--min-scratch-gib", str(min_scratch_gib)]
        if reviews:
            argv.extend(("--reviews", str(reviews)))
        argv.extend(("--pilot-receipt", str(pilot)))
        processes.append(subprocess.Popen(argv,
                                          cwd=Path(__file__).resolve().parents[2]))
    return [process.wait() for process in processes]
