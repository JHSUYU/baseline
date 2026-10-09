"""Resumable, bounded Mallory case dispatcher for node0/node1/node2.

The scheduler knows only whether a case command ran.  Scientific outcomes are
owned by the case runner and must not be inferred from the process exit code.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid

try:
    from .worker import atomic_json
except ImportError:
    from worker import atomic_json


CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
WORKER = Path(__file__).with_name("worker.py").resolve()
DEFAULT_KEY = Path.home() / ".ssh/id_ed25519_nodes"
AGENT_JAR = WORKER.parents[1] / "instrumentation/target/mallory-agent.jar"
TERMINAL_STATUSES = ["budget_exhausted", "queue_exhausted", "healthy_seed_invalid",
                     "healthy_node_identity_missing", "healthy_seed_ambiguous",
                     "healthy_no_injectable_door", "healthy_attestation_failed",
                     "fault_trials_not_attested", "calibration_complete"]


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


@contextmanager
def case_lock(case_dir: Path):
    case_dir.mkdir(parents=True, exist_ok=True)
    with (case_dir / "claim.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def worker_busy(case_dir: Path) -> bool:
    with (case_dir / "worker.lock").open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(lock, fcntl.LOCK_UN)
        return False


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def load_cases(path: Path, command_override: list[str] | None) -> tuple[list[dict], dict]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    raw_cases = manifest.get("cases", manifest.get("checks"))
    if not isinstance(raw_cases, list):
        raise ValueError("manifest needs a cases or checks array")
    result = []
    seen = set()
    for row in raw_cases:
        if isinstance(row, str):
            row = {"case_id": row}
        if not isinstance(row, dict):
            raise ValueError("each case must be an object or case ID string")
        case_id = row.get("case_id", row.get("id"))
        if not isinstance(case_id, str) or not CASE_ID.fullmatch(case_id):
            raise ValueError(f"invalid case ID: {case_id!r}")
        if case_id in seen:
            raise ValueError(f"duplicate case ID: {case_id}")
        seen.add(case_id)
        command = row.get("command", command_override or manifest.get("default_command"))
        if command is not None and (not isinstance(command, list) or not command or not all(isinstance(s, str) for s in command)):
            raise ValueError(f"{case_id}: command must be a nonempty argv list")
        result.append({**row, "case_id": case_id, "command": command})
    return result, manifest


def hosts_from_config(path: Path | None, local_slots: int) -> list[dict]:
    if path:
        config = json.loads(path.read_text(encoding="utf-8"))
        hosts = config["hosts"] if isinstance(config, dict) else config
    else:
        hosts = [
            {"name": "node0", "kind": "local", "slots": local_slots},
            {"name": "node1", "kind": "ssh", "address": "ZhenyuLi@node1", "slots": 4},
            {"name": "node2", "kind": "ssh", "address": "ZhenyuLi@node2", "slots": 4},
        ]
    names = set()
    for host in hosts:
        if host["name"] in names or not CASE_ID.fullmatch(host["name"]):
            raise ValueError(f"invalid or duplicate host: {host['name']}")
        names.add(host["name"])
        if host["kind"] not in ("local", "ssh") or int(host["slots"]) < 1:
            raise ValueError(f"invalid host settings: {host}")
        if host["kind"] == "ssh" and not host.get("address"):
            raise ValueError(f"SSH host needs address: {host['name']}")
    return hosts


def ssh_prefix(host: dict, key: Path) -> list[str]:
    return ["ssh", "-T", "-i", str(key), "-o", "IdentitiesOnly=yes",
            "-o", "BatchMode=yes", "-o", "ConnectTimeout=4",
            "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=2",
            host["address"]]


def free_bytes(host: dict, key: Path, path: Path) -> int:
    if host["kind"] == "local":
        return shutil.disk_usage(path).free
    script = "import shutil,sys; print(shutil.disk_usage(sys.argv[1]).free)"
    command = ssh_prefix(host, key) + [shlex.join(["python3", "-c", script, str(path)])]
    result = subprocess.run(command, capture_output=True, text=True, timeout=12)
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[:240] or f"disk probe exited {result.returncode}")
    return int(result.stdout.strip())


def remote_hash(host: dict, key: Path, path: Path) -> str:
    command = ssh_prefix(host, key) + [shlex.join(["sha256sum", str(path)])]
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[:240] or f"hash probe exited {result.returncode}")
    return result.stdout.split()[0]


def local_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_host(host: dict, key: Path, shared_paths: list[Path],
               min_free_bytes: int = 0) -> tuple[bool, str]:
    if host["kind"] == "local":
        try:
            free = shutil.disk_usage(shared_paths[0]).free
        except OSError as exc:
            return False, f"local disk probe failed: {exc}"
        if free < min_free_bytes:
            return False, (f"{free / 1024**3:.2f} GiB free below "
                           f"{min_free_bytes / 1024**3:.2f} GiB admission")
        return True, f"local; {free / 1024**3:.2f} GiB free"
    if not key.is_file():
        return False, f"SSH key missing: {key}"
    path_checks = " && ".join(f"test -w {shlex.quote(str(path))}" for path in shared_paths)
    script = f"{path_checks} && test -f {shlex.quote(str(WORKER))} && command -v flock >/dev/null"
    try:
        proc = subprocess.run(ssh_prefix(host, key) + [shlex.join(["/bin/sh", "-lc", script])],
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if proc.returncode:
        return False, (proc.stderr.strip() or f"SSH probe exited {proc.returncode}")[:240]
    # A reachable path with the same spelling is not necessarily shared across
    # CloudLab nodes.  Never hand a remote worker a node0-local spec/lease.
    sentinel = shared_paths[0] / f".fs-probe-{uuid.uuid4().hex}"
    token = uuid.uuid4().hex
    try:
        sentinel.write_text(token, encoding="utf-8")
        script = "import pathlib,sys; print(pathlib.Path(sys.argv[1]).read_text())"
        check = subprocess.run(ssh_prefix(host, key) + [shlex.join(["python3", "-c", script,
                                                                    str(sentinel)])],
                               capture_output=True, text=True, timeout=12)
        if check.returncode or check.stdout.strip() != token:
            return False, "state root is not shared; use disjoint local shards"
    except (OSError, subprocess.TimeoutExpired):
        return False, "state root is not shared; use disjoint local shards"
    finally:
        sentinel.unlink(missing_ok=True)
    try:
        for local in (WORKER, AGENT_JAR):
            if not local.is_file() or remote_hash(host, key, local) != local_hash(local):
                return False, f"staged file absent or stale: {local}"
        free = free_bytes(host, key, shared_paths[0])
        if free < min_free_bytes:
            return False, f"{free / 1024**3:.2f} GiB free below {min_free_bytes / 1024**3:.2f} GiB admission"
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        return False, f"remote probe failed: {exc}"
    return True, f"SSH ready; staged code matches; {free / 1024**3:.2f} GiB free"


def format_command(case: dict, manifest: dict, context: dict) -> list[str]:
    if case["command"] is None:
        raise ValueError(f"{case['case_id']}: missing case command")
    def expand(piece: str) -> str:
        def replace(match: re.Match) -> str:
            name = match.group(1)
            if name not in context:
                raise ValueError(f"{case['case_id']}: unknown command placeholder {name}")
            return context[name]
        return PLACEHOLDER.sub(replace, piece)
    return [expand(piece) for piece in case["command"]]


def verify_runtime_artifacts(config: dict) -> None:
    artifacts = config.get("runtime_artifacts", [])
    if not isinstance(artifacts, list):
        raise ValueError("runtime_artifacts must be a list")
    pinned = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ValueError("runtime artifact must be an object")
        path = Path(artifact.get("path", ""))
        expected = artifact.get("sha256")
        if (not path.is_absolute() or not isinstance(expected, str)
                or not re.fullmatch(r"[0-9a-f]{64}", expected)
                or not path.is_file() or local_hash(path) != expected):
            raise ValueError(f"runtime artifact missing or hash mismatch: {path}")
        pinned.add(str(path.resolve()))
    adapter = config.get("agent_properties", {}).get("adapter.jar")
    if adapter and str(Path(adapter).resolve()) not in pinned:
        raise ValueError("adapter jar must be pinned in runtime_artifacts")


def validate_case_configs(cases: list[dict], inventory_path: Path,
                          config_template: str, phase: str = "both",
                          data_root: Path | None = None,
                          source_reference: dict | None = None,
                          calibration_output_root: Path = Path("data/mallory/calibration")) -> list[dict]:
    """Admit only configured cluster-test cases with an inventory source pin."""
    try:
        from Mallory.core.campaign import validate_config
    except ImportError:
        # Direct script invocation from a non-repository CWD.
        sys.path.insert(0, str(WORKER.parents[2]))
        from Mallory.core.campaign import validate_config
    try:
        from .verify_sources import case_expected_files, sha256_file
    except ImportError:
        from verify_sources import case_expected_files, sha256_file
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    rows = {row["case_id"]: row for row in inventory["cases"]}
    admitted = []
    for case in cases:
        case_id = case["case_id"]
        row = rows.get(case_id)
        if row is None:
            print(json.dumps({"case_id": case_id, "status": "inventory_missing"}), flush=True)
            continue
        eligibility = row.get("eligibility", {})
        if eligibility.get("may_dispatch_healthy_seed") is False:
            print(json.dumps({"case_id": case_id,
                              "status": eligibility.get("state", "healthy_seed_ineligible")}),
                  flush=True)
            continue
        if not row.get("workload", {}).get("test_source_path"):
            print(json.dumps({"case_id": case_id, "status": "no_mapped_cluster_test"}), flush=True)
            continue
        path = Path(config_template.format(case_id=case_id)).resolve()
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
            if phase == "campaign" and config.get("mapping", {}).get("status") != "runtime_attested":
                if data_root is None or source_reference is None:
                    raise ValueError("campaign promotion needs data root and source reference")
                try:
                    from .promote import promote
                except ImportError:
                    from promote import promote
                path = promote(path, calibration_output_root / case_id,
                               data_root / "promoted_configs" / f"{case_id}.json",
                               row, source_reference)
                config = json.loads(path.read_text(encoding="utf-8"))
            validate_config(config)
            source_root = Path(row["provenance"]["source_root"]).resolve()
            if config["case_id"] != case_id or config["system"] != row["system"]:
                raise ValueError("case ID or system differs from inventory")
            cwd = Path(config["cwd"]).resolve()
            overlay_path = config.get("source_overlay_receipt")
            equivalent_path = config.get("source_equivalent_root")
            if overlay_path and equivalent_path:
                raise ValueError("patched overlay and clean equivalent root are exclusive")
            if overlay_path:
                receipt = json.loads(Path(overlay_path).read_text(encoding="utf-8"))
                if Path(receipt["base_root"]).resolve() != source_root:
                    raise ValueError("overlay base root differs from inventory")
                overlay_root = Path(receipt["patched_root"]).resolve()
                if not cwd.is_relative_to(overlay_root):
                    raise ValueError("cluster test cwd is outside declared patched root")
            elif equivalent_path:
                equivalent_root = Path(equivalent_path)
                if not equivalent_root.is_absolute() or not equivalent_root.is_dir():
                    raise ValueError("clean equivalent source root missing or relative")
                if not cwd.is_relative_to(equivalent_root.resolve()):
                    raise ValueError("cluster test cwd is outside clean equivalent root")
            elif not cwd.is_relative_to(source_root):
                raise ValueError("cluster test cwd is outside inventory source root")
            if config["cluster_test"] != row["workload"]["selected_selector"]:
                raise ValueError("cluster test selector differs from inventory")
            if not config.get("agent_jar") or not Path(config["agent_jar"]).is_file():
                raise ValueError("instrumentation agent jar is missing")
            verify_runtime_artifacts(config)
            for source_file, expected_hash in case_expected_files(row, config):
                if not source_file.is_file() or sha256_file(source_file) != expected_hash:
                    raise ValueError(f"target/test source hash mismatch: {source_file}")
            mapping = config.get("mapping", {})
            compiled = mapping.get("compiled_jar")
            compiled_hash = mapping.get("compiled_jar_sha256")
            if compiled or compiled_hash:
                if not compiled or not compiled_hash or not Path(compiled).is_file() or sha256_file(Path(compiled)) != compiled_hash:
                    raise ValueError("mapped compiled artifact hash mismatch")
            if mapping.get("status") == "runtime_attested":
                if not (mapping.get("healthy_seed_verified")
                        and mapping.get("node_identity_binding_verified")
                        and mapping.get("verified_healthy_probe")
                        and re.fullmatch(r"[0-9a-f]{64}",
                                         str(config.get("expected_target_class_sha256", "")))):
                    raise ValueError("campaign mapping lacks healthy runtime attestation")
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            print(json.dumps({"case_id": case_id, "status": "config_unvalidated",
                              "reason": str(exc)[:240]}), flush=True)
            continue
        case_phase = "campaign" if mapping.get("status") == "runtime_attested" else "calibration"
        admitted_case = {**case, "_inventory": row, "_case_config_path": str(path),
                         "_case_config_sha256": local_hash(path),
                         "_phase": case_phase,
                         "_equivalent_root": config.get("source_equivalent_root")}
        if case_phase == "calibration":
            admitted_case["command"] = ["python3", "-m", "Mallory.core.campaign",
                                         "--config", str(path), "--out",
                                         str(calibration_output_root / case_id), "--calibration-only"]
            admitted_case["completion_file"] = str(calibration_output_root / case_id / "result.json")
            admitted_case["terminal_statuses"] = ["calibration_complete", "healthy_seed_invalid",
                                                  "healthy_node_identity_missing", "healthy_seed_ambiguous",
                                                  "healthy_no_injectable_door", "healthy_attestation_failed"]
        else:
            campaign_root = data_root / "cases" / case_id
            admitted_case["command"] = ["python3", "-m", "Mallory.core.campaign",
                                         "--config", str(path), "--out", str(campaign_root)]
            admitted_case["completion_file"] = str(campaign_root / "result.json")
            admitted_case["terminal_statuses"] = ["budget_exhausted", "queue_exhausted",
                                                  "healthy_seed_invalid", "healthy_node_identity_missing",
                                                  "healthy_seed_ambiguous", "healthy_no_injectable_door",
                                                  "healthy_attestation_failed", "fault_trials_not_attested"]
        admitted.append(admitted_case)
    return admitted


def case_state_dir(root: Path, case: dict) -> Path:
    phase = case.get("_phase")
    return root / phase / "cases" / case["case_id"] if phase else root / "cases" / case["case_id"]


def receipt_for_lease(case_dir: Path, lease: dict | None) -> dict | None:
    if not lease:
        return None
    path = case_dir / "attempts" / lease["attempt_id"] / "exit.json"
    receipt = read_json(path)
    if receipt and receipt.get("attempt_id") == lease["attempt_id"]:
        return receipt
    return None


def validate_completion(case_dir: Path, receipt: dict) -> dict:
    """Keep process success distinct from a terminal case-runner record."""
    receipt = dict(receipt)
    spec = read_json(case_dir / "attempts" / receipt["attempt_id"] / "spec.json") or {}
    marker = spec.get("completion_file")
    if not marker:
        return receipt
    marker_path = Path(marker)
    try:
        summary = read_json(marker_path)
        marker_time = marker_path.stat().st_mtime
    except (FileNotFoundError, json.JSONDecodeError):
        summary, marker_time = None, 0
    terminal = spec.get("terminal_statuses", TERMINAL_STATUSES)
    valid = (isinstance(summary, dict) and summary.get("case_id") == receipt["case_id"]
             and summary.get("status") in terminal
             and summary.get("last_dispatch_attempt_id") == receipt["attempt_id"]
             and marker_time >= receipt.get("started_at", 0) - 5)
    receipt["scientific_completed"] = valid
    receipt["scientific_result_status"] = summary.get("status") if isinstance(summary, dict) else None
    if receipt["status"] == "command_succeeded" and not valid:
        receipt["status"] = "result_missing"
        receipt["error"] = f"terminal case result absent or invalid: {marker}"
    return receipt


def recover_case(case_dir: Path) -> dict | None:
    """Commit a finished worker receipt left by a previous coordinator."""
    with case_lock(case_dir):
        result = read_json(case_dir / "result.json")
        if result and result.get("status") == "command_succeeded":
            validated = validate_completion(case_dir, result)
            if validated != result:
                atomic_json(case_dir / "result.json", validated)
                result = validated
        lease = read_json(case_dir / "lease.json")
        receipt = receipt_for_lease(case_dir, lease)
        if receipt and (result is None or result.get("attempt_id") != receipt["attempt_id"]):
            receipt = validate_completion(case_dir, receipt)
            atomic_json(case_dir / "result.json", receipt)
            (case_dir / "lease.json").unlink(missing_ok=True)
            return receipt
        return result


def classify_case(case_dir: Path, retry_failed: bool) -> str:
    result = recover_case(case_dir)
    if result:
        if result["status"] == "command_succeeded":
            return "command_succeeded"
        if result["status"] in ("result_missing", "launcher_failed", "dispatch_failed"):
            return "pending"
        if not retry_failed:
            return "command_failed"
    with case_lock(case_dir):
        if worker_busy(case_dir):
            return "running"
        lease = read_json(case_dir / "lease.json")
        if lease:
            # The coordinator may have died before launching the worker.
            if lease.get("coordinator_host") == socket.gethostname() and pid_alive(int(lease.get("coordinator_pid", -1))):
                return "running"
            if lease.get("expires_at", 0) > time.time():
                return "leased"
        return "pending"


def claim(case_dir: Path, host: dict, ttl: float, retry_failed: bool) -> str | None:
    with case_lock(case_dir):
        result = read_json(case_dir / "result.json")
        if result:
            if result.get("status") == "command_succeeded":
                return None
            if result.get("status") == "command_failed" and not retry_failed:
                return None
        if worker_busy(case_dir):
            return None
        lease = read_json(case_dir / "lease.json")
        if lease:
            if receipt_for_lease(case_dir, lease):
                return None
            if lease.get("coordinator_host") == socket.gethostname() and pid_alive(int(lease.get("coordinator_pid", -1))):
                return None
            if lease.get("expires_at", 0) > time.time():
                return None
        attempt_id = time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + "-" + uuid.uuid4().hex[:12]
        atomic_json(case_dir / "lease.json", {
            "attempt_id": attempt_id, "host": host["name"], "claimed_at": time.time(),
            "expires_at": time.time() + ttl,
            "coordinator_host": socket.gethostname(), "coordinator_pid": os.getpid(),
        })
        return attempt_id


def renew(case_dir: Path, attempt_id: str, ttl: float) -> None:
    with case_lock(case_dir):
        lease = read_json(case_dir / "lease.json")
        if lease and lease["attempt_id"] == attempt_id:
            lease["expires_at"] = time.time() + ttl
            atomic_json(case_dir / "lease.json", lease)


def execute(case: dict, manifest: dict, host: dict, args: argparse.Namespace) -> dict:
    case_id = case["case_id"]
    if host["name"] in ("node1", "node2"):
        try:
            free = free_bytes(host, args.ssh_key, args.state_root)
            needed = int((args.remote_reserve_gib + args.remote_case_gib) * 1024 ** 3)
            if free < needed:
                return {"case_id": case_id, "host": host["name"],
                        "status": "host_disk_unavailable", "free_bytes": free,
                        "required_bytes": needed}
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            return {"case_id": case_id, "host": host["name"],
                    "status": "host_unavailable", "reason": str(exc)[:240]}
    if case.get("_inventory"):
        try:
            try:
                from .verify_sources import verify_case_files
            except ImportError:
                from verify_sources import verify_case_files
            root = case["_inventory"]["provenance"]["source_root"]
            if root not in host.get("_verified_roots", set()):
                return {"case_id": case_id, "host": host["name"],
                        "status": "source_unverified", "source_root": root}
            config = json.loads(Path(case["_case_config_path"]).read_text(encoding="utf-8"))
            if local_hash(Path(case["_case_config_path"])) != case["_case_config_sha256"]:
                return {"case_id": case_id, "host": host["name"],
                        "status": "config_changed_after_admission"}
            verify_runtime_artifacts(config)
            equivalent_root = config.get("source_equivalent_root")
            if equivalent_root and equivalent_root not in host.get("_verified_equivalents", set()):
                try:
                    from .verify_sources import verify_from_reference
                except ImportError:
                    from verify_sources import verify_from_reference
                reference = json.loads(args.source_reference.read_text(encoding="utf-8"))
                evidence = verify_from_reference(host, args.ssh_key, Path(root),
                                                 case["_inventory"]["provenance"]["source_commit"],
                                                 reference, Path(equivalent_root))
                if not evidence["content_match"]:
                    return {"case_id": case_id, "host": host["name"],
                            "status": "source_unverified", "reason": "clean equivalent source fingerprint differs"}
            valid, reason = verify_case_files(host, args.ssh_key, case["_inventory"], config)
            if not valid:
                return {"case_id": case_id, "host": host["name"],
                        "status": "source_unverified", "reason": reason}
            if host["kind"] == "ssh":
                config_path = Path(case["_case_config_path"])
                if remote_hash(host, args.ssh_key, config_path) != local_hash(config_path):
                    return {"case_id": case_id, "host": host["name"],
                            "status": "config_unstaged"}
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            return {"case_id": case_id, "host": host["name"],
                    "status": "source_unverified", "reason": str(exc)[:240]}
    case_dir = case_state_dir(args.state_root, case)
    attempt_id = claim(case_dir, host, args.lease_seconds, args.retry_failed)
    if attempt_id is None:
        return {"case_id": case_id, "status": "already_running_or_finished"}
    attempt = case_dir / "attempts" / attempt_id
    attempt.mkdir(parents=True)
    scratch = args.scratch_root / case_id / attempt_id
    build = args.build_root / case_id / attempt_id
    scratch.mkdir(parents=True)
    build.mkdir(parents=True)
    context = {"case_id": case_id, "scratch": str(scratch), "build": str(build),
               "state": str(case_dir), "attempt_id": attempt_id, "host": host["name"]}
    cwd = Path(case.get("cwd", manifest.get("default_cwd", args.default_cwd))).resolve()
    try:
        command = format_command(case, manifest, context)
        completion_template = case.get("completion_file", manifest.get("default_completion_file", args.completion_file_template))
        completion_file = Path(completion_template.format_map(context)).resolve() if completion_template else None
        if not cwd.is_dir():
            raise ValueError(f"working directory does not exist: {cwd}")
        lane_lock = None
        if args.lane_id:
            args.lane_lock_root.mkdir(parents=True, exist_ok=True)
            lane_lock = args.lane_lock_root / f"{args.lane_id}.lock"
        spec = {
            "case_id": case_id, "attempt_id": attempt_id,
            "case_config_sha256": case.get("_case_config_sha256"),
            "host": host["name"], "attempt_dir": str(attempt),
            "worker_lock": str(case_dir / "worker.lock"),
            "lane_id": args.lane_id or None,
            "lane_lock": str(lane_lock) if lane_lock else None,
            "command": command, "cwd": str(cwd),
            "completion_file": str(completion_file) if completion_file else None,
            "terminal_statuses": case.get("terminal_statuses", manifest.get("terminal_statuses", TERMINAL_STATUSES)),
            "timeout_seconds": float(case.get("timeout_seconds", args.timeout_seconds)),
            "environment": {
                "MALLORY_CASE_ID": case_id, "MALLORY_ATTEMPT_ID": attempt_id,
                "MALLORY_SCRATCH": str(scratch), "MALLORY_BUILD": str(build),
                "MALLORY_CASE_STATE": str(case_dir), "MALLORY_HOST": host["name"],
                "MALLORY_LANE_ID": args.lane_id or "",
            },
        }
        if args.core_release_manifest:
            release_root = args.core_release_manifest.parent
            spec["core_release_manifest"] = str(args.core_release_manifest)
            spec["core_release_id"] = args._core_release_id
            spec["environment"]["PYTHONPATH"] = (
                str(release_root) + os.pathsep + str(Path(__file__).resolve().parents[2]) +
                (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""))
            spec["environment"]["MALLORY_CORE_RELEASE_ID"] = args._core_release_id
        atomic_json(attempt / "spec.json", spec)
        if host["kind"] == "local":
            launch = [sys.executable, str(WORKER), str(attempt / "spec.json")]
        else:
            remote_script = shlex.join(["python3", str(WORKER), str(attempt / "spec.json")])
            launch = ssh_prefix(host, args.ssh_key) + [shlex.join(["/bin/sh", "-lc", remote_script])]
        with (attempt / "launcher.log").open("ab") as launch_log:
            proc = subprocess.Popen(launch, stdout=launch_log, stderr=launch_log,
                                    start_new_session=True)
            while proc.poll() is None:
                time.sleep(min(args.heartbeat_seconds, 2.0))
                renew(case_dir, attempt_id, args.lease_seconds)
        receipt = read_json(attempt / "exit.json")
        if receipt is None:
            receipt = {
                "case_id": case_id, "attempt_id": attempt_id, "host": host["name"],
                "status": "launcher_failed", "exit_code": proc.returncode,
                "error": "worker did not write an exit receipt; inspect launcher.log",
                "finished_at": time.time(),
            }
        else:
            receipt = validate_completion(case_dir, receipt)
        with case_lock(case_dir):
            atomic_json(case_dir / "result.json", receipt)
            current = read_json(case_dir / "lease.json")
            if current and current["attempt_id"] == attempt_id:
                (case_dir / "lease.json").unlink()
        return receipt
    except Exception as exc:
        receipt = {"case_id": case_id, "attempt_id": attempt_id, "host": host["name"],
                   "status": "dispatch_failed", "error": f"{type(exc).__name__}: {exc}",
                   "finished_at": time.time()}
        with case_lock(case_dir):
            atomic_json(case_dir / "result.json", receipt)
            (case_dir / "lease.json").unlink(missing_ok=True)
        return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--inventory", type=Path,
                        help="source pins and cluster-test mappings; required for the 102-check selection")
    parser.add_argument("--source-reference", type=Path,
                        default=Path("Mallory/dispatch/source_reference.json"),
                        help="clean node0 tracked-file digest manifest for hosts without Git metadata")
    parser.add_argument("--case-config-template", default="Mallory/cases/{case_id}.json")
    parser.add_argument("--calibration-output-root", type=Path,
                        default=Path("data/mallory/calibration"),
                        help="versioned calibration output root; use a new root after config changes")
    parser.add_argument("--hold-file", type=Path,
                        default=Path("Mallory/dispatch/shards/holds.json"),
                        help="case IDs reserved for independent active or completed campaigns")
    parser.add_argument("--phase", choices=("calibration", "campaign", "both"), default="both")
    parser.add_argument("--hosts-file", type=Path)
    parser.add_argument("--state-root", type=Path, default=Path("data/mallory/dispatch"))
    parser.add_argument("--scratch-root", type=Path, default=Path("/tmp/mallory-scratch"))
    parser.add_argument("--build-root", type=Path, default=Path("/tmp/mallory-build"))
    parser.add_argument("--lane-id", default="",
                        help="host-local isolated source/build/JVM lane; worker holds its flock")
    parser.add_argument("--lane-lock-root", type=Path, default=Path("/tmp/mallory-lanes"))
    parser.add_argument("--core-release-manifest", type=Path,
                        help="immutable Mallory/core snapshot; required for inventory fault campaigns")
    parser.add_argument("--default-cwd", type=Path, default=Path.cwd())
    parser.add_argument("--ssh-key", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--command-json", help="argv JSON, e.g. '[\"python3\",\"runner.py\",\"{case_id}\"]'")
    parser.add_argument("--completion-file-template", help="terminal case result JSON path; {case_id} is allowed")
    parser.add_argument("--max-parallel", type=int, default=10)
    parser.add_argument("--local-slots", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=7200)
    parser.add_argument("--lease-seconds", type=float, default=120)
    parser.add_argument("--heartbeat-seconds", type=float, default=10)
    parser.add_argument("--remote-reserve-gib", type=float, default=5,
                        help="disk space left unused on each remote host")
    parser.add_argument("--remote-case-gib", type=float, default=4,
                        help="estimated disk headroom required per concurrent remote case")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--only", nargs="*", help="run only these case IDs")
    parser.add_argument("--list", action="store_true", help="read existing status without mutation")
    parser.add_argument("--dry-run", action="store_true", help="show command plans without launching")
    parser.add_argument("--probe-hosts", action="store_true", help="check host availability only")
    parser.add_argument("--validate-only", action="store_true",
                        help="validate configs, source content, and host capacity without launching")
    args = parser.parse_args(argv)
    if args.lane_id and not CASE_ID.fullmatch(args.lane_id):
        parser.error("lane ID must contain only letters, digits, periods, underscores, or hyphens")
    if (min(args.max_parallel, args.local_slots) < 1
            or min(args.lease_seconds, args.heartbeat_seconds, args.timeout_seconds,
                   args.remote_reserve_gib, args.remote_case_gib) <= 0):
        parser.error("parallelism and durations must be positive")
    command_override = json.loads(args.command_json) if args.command_json else None
    cases, manifest = load_cases(args.manifest, command_override)
    if args.only:
        wanted = set(args.only)
        unknown = wanted - {case["case_id"] for case in cases}
        if unknown:
            parser.error(f"unknown case IDs: {sorted(unknown)}")
        cases = [case for case in cases if case["case_id"] in wanted]
    hosts = hosts_from_config(args.hosts_file, args.local_slots)
    holds = json.loads(args.hold_file.read_text(encoding="utf-8")) if args.hold_file.is_file() else {}
    if args.list:
        for case in cases:
            phases = ("calibration", "campaign") if args.phase == "both" else (args.phase,)
            statuses = {}
            for phase in phases:
                case_dir = args.state_root / phase / "cases" / case["case_id"]
                result = read_json(case_dir / "result.json")
                lease = read_json(case_dir / "lease.json")
                result = result or receipt_for_lease(case_dir, lease)
                statuses[phase] = result["status"] if result else "running" if lease else "pending"
            print(json.dumps({"case_id": case["case_id"], "status": "held_external"
                              if case["case_id"] in holds else statuses,
                              "hold_reason": holds.get(case["case_id"], {}).get("reason")}))
        return 0
    if args.dry_run:
        for case in cases:
            context = {"case_id": case["case_id"], "scratch": "<scratch>",
                       "build": "<build>", "state": "<state>", "attempt_id": "<attempt>", "host": "<host>"}
            print(json.dumps({"case_id": case["case_id"],
                              "held_external": case["case_id"] in holds,
                              "command": format_command(case, manifest, context) if case["command"] else None}))
        return 0
    core_release = None
    if args.core_release_manifest:
        try:
            try:
                from .core_release import verify as verify_core_release
            except ImportError:
                from core_release import verify as verify_core_release
            args.core_release_manifest = args.core_release_manifest.resolve()
            core_release = verify_core_release(args.core_release_manifest)
            args._core_release_id = core_release["release_id"]
            release_root = str(args.core_release_manifest.parent)
            if release_root not in sys.path:
                sys.path.insert(0, release_root)
            from Mallory.core import campaign as campaign_module
            if Path(campaign_module.__file__).resolve().parents[2] != args.core_release_manifest.parent:
                raise ValueError("scheduler did not load the pinned core release")
        except (OSError, ValueError, KeyError) as exc:
            parser.error(f"core release verification failed: {exc}")
    if args.inventory and args.phase in ("campaign", "both") and not args.probe_hosts and not core_release:
        parser.error("inventory fault campaigns require --core-release-manifest")
    if holds and not args.probe_hosts:
        for case in cases:
            if case["case_id"] in holds:
                print(json.dumps({"case_id": case["case_id"], "status": "held_external",
                                  "reason": holds[case["case_id"]]["reason"]}), flush=True)
        cases = [case for case in cases if case["case_id"] not in holds]
    if "checks" in manifest and not args.inventory and not args.probe_hosts:
        parser.error("the 102-check selection requires --inventory before any trial")
    source_reference = None
    if args.inventory and not args.probe_hosts:
        if not args.source_reference.is_file():
            parser.error(f"source reference missing: {args.source_reference}")
        source_reference = json.loads(args.source_reference.read_text(encoding="utf-8"))
        if source_reference.get("inventory_sha256") != local_hash(args.inventory):
            parser.error("source reference inventory digest differs from current inventory")
    original_count = len(cases)
    if args.inventory and not args.probe_hosts:
        cases = validate_case_configs(cases, args.inventory, args.case_config_template,
                                      args.phase, args.state_root.resolve().parents[1],
                                      source_reference, args.calibration_output_root.resolve())
        if args.phase != "both":
            cases = [case for case in cases if case["_phase"] == args.phase]
    args.state_root = args.state_root.resolve()
    args.scratch_root = args.scratch_root.resolve()
    args.build_root = args.build_root.resolve()
    args.lane_lock_root = args.lane_lock_root.resolve()
    args.default_cwd = args.default_cwd.resolve()
    for path in (args.state_root, args.scratch_root, args.build_root):
        path.mkdir(parents=True, exist_ok=True)
    shared_paths = [args.state_root, args.scratch_root, args.build_root]
    minimum_remote = int((args.remote_reserve_gib + args.remote_case_gib) * 1024 ** 3)
    availability = {host["name"]: probe_host(host, args.ssh_key, shared_paths,
                                              minimum_remote) for host in hosts}
    for host in hosts:
        ok, reason = availability[host["name"]]
        print(json.dumps({"host": host["name"], "available": ok, "reason": reason}), flush=True)
    if args.probe_hosts:
        return 0
    available_hosts = [host for host in hosts if availability[host["name"]][0]]
    if core_release:
        release_files = {"manifest.json": local_hash(args.core_release_manifest),
                         **core_release["files"]}
        verified_hosts = []
        for host in available_hosts:
            release_root = args.core_release_manifest.parent
            try:
                for relative, expected in release_files.items():
                    actual = release_root / relative
                    observed = (local_hash(actual) if host["kind"] == "local" else
                                remote_hash(host, args.ssh_key, actual))
                    if observed != expected:
                        raise ValueError(f"core release hash differs: {relative}")
            except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
                print(json.dumps({"host": host["name"], "core_release_verified": False,
                                  "reason": str(exc)[:240]}), flush=True)
                continue
            print(json.dumps({"host": host["name"], "core_release_verified": True,
                              "release_id": core_release["release_id"]}), flush=True)
            verified_hosts.append(host)
        available_hosts = verified_hosts
    if args.inventory:
        try:
            try:
                from .verify_sources import verify_from_reference
            except ImportError:
                from verify_sources import verify_from_reference
        except ImportError as exc:
            parser.error(f"source verifier unavailable: {exc}")
        expected_roots = {}
        for case in cases:
            provenance = case["_inventory"]["provenance"]
            root, commit = provenance["source_root"], provenance["source_commit"]
            if root in expected_roots and expected_roots[root] != commit:
                parser.error(f"conflicting inventory commits for {root}")
            expected_roots[root] = commit
        for host in available_hosts:
            host["_verified_roots"] = set()
            host["_verified_equivalents"] = set()
            for root, commit in sorted(expected_roots.items()):
                try:
                    verdict = verify_from_reference(host, args.ssh_key, Path(root), commit,
                                                    source_reference)
                    if verdict["content_match"]:
                        host["_verified_roots"].add(root)
                    print(json.dumps(verdict, sort_keys=True), flush=True)
                except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError,
                        subprocess.TimeoutExpired) as exc:
                    print(json.dumps({"host": host["name"], "source_root": root,
                                      "content_match": False, "reason": str(exc)[:240]}), flush=True)
            seen_equivalents = set()
            for case in cases:
                equivalent = case.get("_equivalent_root")
                if not equivalent or equivalent in seen_equivalents:
                    continue
                seen_equivalents.add(equivalent)
                provenance = case["_inventory"]["provenance"]
                try:
                    verdict = verify_from_reference(host, args.ssh_key,
                                                    Path(provenance["source_root"]),
                                                    provenance["source_commit"],
                                                    source_reference, Path(equivalent))
                    if verdict["content_match"]:
                        host["_verified_equivalents"].add(equivalent)
                    print(json.dumps(verdict, sort_keys=True), flush=True)
                except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError,
                        subprocess.TimeoutExpired) as exc:
                    print(json.dumps({"host": host["name"], "actual_root": equivalent,
                                      "content_match": False, "reason": str(exc)[:240]}), flush=True)
    for host in available_hosts:
        if host["name"] in ("node1", "node2"):
            free = free_bytes(host, args.ssh_key, args.state_root)
            disk_slots = max(0, int((free - args.remote_reserve_gib * 1024 ** 3)
                                    // (args.remote_case_gib * 1024 ** 3)))
            host["_effective_slots"] = min(int(host["slots"]), disk_slots)
        else:
            host["_effective_slots"] = int(host["slots"])
        print(json.dumps({"host": host["name"], "effective_slots": host["_effective_slots"]}), flush=True)
    slots = []
    for level in range(max((host["_effective_slots"] for host in available_hosts), default=0)):
        slots.extend(host for host in available_hosts if host["_effective_slots"] > level)
    slots = slots[:args.max_parallel]
    if not slots:
        print("no available hosts", file=sys.stderr)
        return 2
    pending = [case for case in cases if classify_case(case_state_dir(args.state_root, case), args.retry_failed) == "pending"]
    missing_command = [case["case_id"] for case in pending if case["command"] is None]
    if missing_command:
        parser.error(f"pending cases lack a command: {missing_command[:8]}"
                     + (f" and {len(missing_command) - 8} more" if len(missing_command) > 8 else ""))
    skipped = len(cases) - len(pending)
    print(json.dumps({"pending": len(pending), "skipped_existing_or_active": skipped,
                      "unconfigured_or_unmapped": original_count - len(cases),
                      "parallel_slots": len(slots)}), flush=True)
    if args.validate_only:
        eligible = sum(any(case.get("_inventory", {}).get("provenance", {}).get("source_root")
                           in host.get("_verified_roots", set()) and
                           (not case.get("_equivalent_root") or
                            case["_equivalent_root"] in host.get("_verified_equivalents", set()))
                           for host in slots)
                       if args.inventory else bool(slots) for case in pending)
        print(json.dumps({"validated_pending": eligible, "phase": args.phase}), flush=True)
        return 0 if eligible or (cases and not pending) else 2
    semaphores = {host["name"]: threading.Semaphore(host["_effective_slots"])
                  for host in available_hosts if host["_effective_slots"]}
    def execute_bounded(case: dict, host: dict) -> dict:
        with semaphores[host["name"]]:
            return execute(case, manifest, host, args)
    with ThreadPoolExecutor(max_workers=len(slots)) as pool:
        futures = []
        for i, case in enumerate(pending):
            suitable = ([host for host in slots
                         if case.get("_inventory", {}).get("provenance", {}).get("source_root")
                         in host.get("_verified_roots", set()) and
                         (not case.get("_equivalent_root") or
                          case["_equivalent_root"] in host.get("_verified_equivalents", set()))]
                        if args.inventory else slots)
            if not suitable:
                print(json.dumps({"case_id": case["case_id"], "status": "source_unverified_on_all_hosts"}), flush=True)
                continue
            futures.append(pool.submit(execute_bounded, case, suitable[i % len(suitable)]))
        for future in as_completed(futures):
            print(json.dumps(future.result(), sort_keys=True), flush=True)
    return 2 if original_count and not cases else 0


if __name__ == "__main__":
    raise SystemExit(main())
