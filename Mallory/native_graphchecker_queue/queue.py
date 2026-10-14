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

from Mallory.native_graphchecker_dispatch.checklist import (
    DEFAULT_INVENTORY, DEFAULT_OWNERSHIP, _native_case_files,
    inspect_case,
    load_ownership, load_reviews,
)
from .inventory_epoch import load_queue_inventory, require_epoch_results_dir

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


def _campaign_running(root: Path) -> bool:
    """A separately launched native campaign keeps this lock for its run."""
    lock_path = root / ".campaign.lock"
    if not lock_path.is_file():
        return False
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        finally:
            # Closing releases a successful probe; a failed probe owns nothing.
            pass
    return False


def completion(item: dict, row: dict, config_file: Path, state_root: Path,
               queue_root: Path, *, native_root: Path | None = None,
               binding_file: Path | None = None,
               config_root: Path | None = None) -> dict[str, Any]:
    """Publish only a terminal result already audited by native inspect_case."""
    if row["terminal_disposition"] not in TERMINAL:
        raise ValueError("native case has no audited terminal disposition")
    case_id = item["case_id"]
    native_root = native_root or state_root / case_id
    conflicts = port_conflict_logs(native_root)
    if conflicts:
        marker = queue_root / "invalid-overlap" / f"{case_id}.json"
        atomic(marker, {"schema_version": 1, "case_id": case_id,
                        "reason": "JUnit listener port collision",
                        "log_paths": conflicts})
        raise ValueError(f"native JUnit port collision requires review: {marker}")
    if (queue_root / "invalid-overlap" / f"{case_id}.json").exists():
        raise ValueError("prior native port collision requires review")
    summary = native_root / "summary.json"
    native_config = obj(config_file)
    receipt = {
        "schema_version": 1, "method": "original_native_graphchecker_campaign",
        "case_id": case_id, "system": item["system"],
        "source_path": item["target"]["source_path"],
        "source_line": item["target"]["source_line"],
        "target_site": item["target"]["site_id"],
        "target_exception": item["target"].get("target_exception"),
        "original_junit": item["workload"].get("selected_selector"),
        "executed_original_junit": (native_config.get("junit", {}).get("class", "")
                                    + "#" + native_config.get("junit", {}).get(
                                        "method", "")),
        "native_case_id": native_config.get("case_id", case_id),
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
    if binding_file is not None:
        receipt["binding_path"] = str(binding_file.resolve())
        receipt["binding_sha256"] = sha(binding_file)
    _same_or_write(queue_root / "completions" / f"{case_id}.json", receipt)
    if "strict_in_target_closure_trials" in row:
        if config_root is None:
            raise ValueError("closure audit requires the binding config root")
        from .coverage import publish_coverage
        # inspect_case has already validated membership against the original
        # per-trial graph summary; pin those exact files for the result table.
        publish_coverage(item, row, config_root, state_root)
    return receipt


def _contains_trial_dir(config: dict[str, Any]) -> bool:
    args = config.get("runner", {}).get("jvm_args", [])
    data_keys = ("build.test.dir", "test.build.data",
                 "test.build.data.basedirectory", "hadoop.tmp.dir",
                 "hadoop.log.dir", "solr.solr.home", "solr.data.dir",
                 "solr.log.dir", "test.data.dir", "derby.system.home")
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
    exact JVM settings that select them. Random-retry is limited to a pinned
    HBase JUnit/source review of nonzero ZooKeeper selection with bind retry.
    These are explicit launch contracts;
    the queue cannot infer a workload's bind behavior from JUnit success.
    """
    if profile.get("schema_version") != 1:
        raise ValueError("invalid isolation profile schema")
    system_policy = profile.get("systems", {}).get(system)
    if not isinstance(system_policy, dict):
        raise ValueError(f"missing port isolation policy for {system}")
    ports = system_policy.get("ports")
    if not isinstance(ports, dict) or ports.get("mode") not in (
            "ephemeral", "assigned", "random_retry"):
        raise ValueError("port policy must be ephemeral, assigned, or random_retry")
    evidence = ports.get("evidence")
    if not isinstance(evidence, dict) or not evidence:
        raise ValueError("port policy lacks pinned source evidence")
    fallback_receipts = ports.get("shared_evidence_receipts", [])
    fallbacks = ports.get("shared_evidence_fallbacks", {})
    if (not isinstance(fallback_receipts, list) or
            not isinstance(fallbacks, dict) or
            (bool(fallback_receipts) != bool(fallbacks))):
        raise ValueError("shared port evidence fallback is incomplete")
    reconstructed = {}
    for receipt_name in fallback_receipts:
        receipt_path = Path(receipt_name)
        if (not receipt_path.is_absolute() or receipt_path.is_symlink() or
                not receipt_path.is_file() or
                evidence.get(receipt_name) != sha(receipt_path)):
            raise ValueError("shared port evidence receipt changed")
        receipt = obj(receipt_path)
        if (receipt.get("schema_version") != 1 or
                receipt.get("kind") != "native_shared_port_evidence_fallback" or
                receipt.get("system") != system or
                not isinstance(receipt.get("replacements"), list) or
                not receipt["replacements"]):
            raise ValueError("shared port evidence receipt is invalid")
        for replacement in receipt["replacements"]:
            if not isinstance(replacement, dict) or set(replacement) != {
                    "original_path", "sha256", "shared_path"}:
                raise ValueError("shared port evidence replacement is invalid")
            original = replacement["original_path"]
            shared = replacement["shared_path"]
            expected = replacement["sha256"]
            if (original in reconstructed or evidence.get(original) != expected or
                    not isinstance(shared, str) or not Path(shared).is_absolute() or
                    Path(shared).is_symlink() or not Path(shared).is_file() or
                    sha(Path(shared)) != expected):
                raise ValueError("shared port source evidence changed")
            reconstructed[original] = {"path": shared, "sha256": expected}
    if reconstructed != fallbacks:
        raise ValueError("shared port evidence fallback differs from receipts")
    for name, expected in evidence.items():
        path = Path(name)
        if (not path.is_absolute() or path.is_symlink() or
                not isinstance(expected, str) or
                (path.is_file() and sha(path) != expected) or
                (not path.is_file() and name not in fallbacks)):
            raise ValueError(f"port isolation evidence changed: {name}")
    if not _contains_trial_dir(config):
        raise ValueError("JUnit needs isolated tmpdir and cluster data directory")
    args = config["runner"]["jvm_args"]
    required = system_policy.get("required_jvm_args", [])
    if (not isinstance(required, list) or
            not all(isinstance(arg, str) and arg in args for arg in required)):
        raise ValueError("missing required JUnit isolation JVM argument")
    if ports["mode"] == "ephemeral":
        case_receipts = ports.get("case_receipts")
        if case_receipts is not None:
            if not isinstance(case_receipts, dict) or case_id not in case_receipts:
                raise ValueError("ephemeral port review does not cover this JUnit")
            receipt_path = Path(case_receipts[case_id])
        else:
            receipt_path = Path(ports.get("receipt", ""))
        if (not receipt_path.is_absolute() or not receipt_path.is_file() or
                str(receipt_path) not in evidence):
            raise ValueError("ephemeral ports require a pinned dynamic-port receipt")
        receipt = obj(receipt_path)
        if (receipt.get("schema_version") != 1 or
                receipt.get("system") != system or
                receipt.get("case_id") not in (None, case_id) or
                receipt.get("all_listeners_bind_port_zero") is not True):
            raise ValueError("dynamic-port receipt does not attest this system")
        source_evidence = receipt.get("evidence", {})
        if (not isinstance(source_evidence, dict) or
                any(evidence.get(name) != digest for name, digest in
                    source_evidence.items())):
            raise ValueError("dynamic-port source evidence differs from profile")
        return {"mode": "ephemeral", "evidence": evidence}
    if ports["mode"] == "random_retry":
        case_receipts = ports.get("case_receipts")
        if case_receipts is not None:
            if not isinstance(case_receipts, dict) or case_id not in case_receipts:
                raise ValueError("HBase random-retry review does not cover this JUnit")
            receipt_path = Path(case_receipts[case_id])
        else:
            receipt_path = Path(ports.get("receipt", ""))
        if (system != "hbase" or not receipt_path.is_absolute() or
                not receipt_path.is_file() or str(receipt_path) not in evidence):
            raise ValueError("HBase random-retry requires pinned source review")
        receipt = obj(receipt_path)
        if (receipt.get("schema_version") != 1 or
                receipt.get("system") != system or
                receipt.get("case_id") != case_id or
                receipt.get("mode") != "source_reviewed_random_retry" or
                receipt.get("zk_random_port_range") != [49152, 65279] or
                receipt.get("zk_bind_exception_retry") is not True or
                receipt.get("hbase_cluster_default_ports_zero") is not True or
                not isinstance(receipt.get("reviewed_source_sha256"), dict) or
                any(evidence.get(name) != digest for name, digest in
                    receipt["reviewed_source_sha256"].items())):
            raise ValueError("HBase random-retry review does not cover this JUnit")
        return {"mode": "random_retry", "evidence": evidence}
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


def _terminal_fingerprint(item: dict, config_root: Path,
                          state_root: Path,
                          source_archive_root: Path | None = None) -> dict[str, Any] | None:
    """Pin the files that define a terminal native checkpoint."""
    config_file, root = _native_case_files(item, config_root, state_root,
                                          source_archive_root)
    checkpoint_path = root / "checkpoint.json"
    summary_path = root / "summary.json"
    if not checkpoint_path.is_file() or not summary_path.is_file():
        return None
    checkpoint = obj(checkpoint_path)
    summary = obj(summary_path)
    config_sha = sha(config_file)
    if (checkpoint.get("terminal") is not True or
            summary.get("terminal") is not True or
            checkpoint.get("case_id") != obj(config_file).get("case_id") or
            summary.get("case_id") != checkpoint.get("case_id") or
            checkpoint.get("config_sha256") != config_sha or
            summary.get("config_sha256") != config_sha):
        return None
    entry = config_root / f"{item['case_id']}.json"
    return {"case_id": item["case_id"], "native_root": str(root.resolve()),
            "inventory_row_sha256": hashlib.sha256(json.dumps(
                item, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "config_sha256": config_sha,
            "checkpoint_sha256": sha(checkpoint_path),
            "summary_sha256": sha(summary_path),
            "binding_sha256": sha(entry) if entry != config_file else None}


def _terminal_cache_path(state_root: Path, case_id: str) -> Path:
    return state_root / ".native-queue" / "audits" / f"{case_id}.json"


def _local_artifact_attestation_valid(audit: dict, fingerprint: dict) -> bool:
    """Permit a remote reader to use only a pinned, local-host full audit."""
    attestation = audit.get("local_artifact_attestation")
    if not isinstance(attestation, dict):
        return False
    host = attestation.get("host")
    local_root = attestation.get("local_root")
    root = Path(fingerprint["native_root"])
    manifests = attestation.get("manifest_sha256")
    trees = attestation.get("trial_tree_sha256")
    count = audit.get("row", {}).get("fault_trials")
    if (not isinstance(host, str) or not host or
            os.uname().nodename != host or
            not isinstance(local_root, str) or not Path(local_root).is_absolute() or
            not isinstance(count, int) or isinstance(count, bool) or count < 0 or
            not isinstance(manifests, dict) or not isinstance(trees, dict) or
            len(manifests) != count + 1 or len(trees) != count + 1):
        return False
    from Mallory.native_graphchecker_dispatch.checklist import _checkpoint_trial_refs
    refs = _checkpoint_trial_refs(root, obj(root / "checkpoint.json"))
    if len(refs) != count + 1:
        return False
    for _, result_path in refs:
        trial = result_path.parent
        path = trial / "local-artifacts.json"
        digest = manifests.get(str(path))
        if (not isinstance(digest, str) or path.is_symlink() or
                not path.is_file() or sha(path) != digest):
            return False
        manifest = obj(path)
        result_path = trial / "result.json"
        if result_path.is_symlink() or not result_path.is_file():
            return False
        result = obj(result_path)
        local = Path(manifest.get("local_attempt_dir", ""))
        if (manifest.get("status") != "closed" or
                manifest.get("host") != host or
                manifest.get("campaign_root") != str(root) or
                manifest.get("trial") != trial.name or
                manifest.get("tree_sha256") != trees.get(trial.name) or
                result.get("local_artifacts_manifest_sha256") != digest or
                not local.is_absolute() or
                not local.is_relative_to(Path(local_root)) or
                not local.is_dir()):
            return False
        links = manifest.get("links")
        if not isinstance(links, dict) or not links:
            return False
        for relative, target in links.items():
            link = trial / relative
            if (not isinstance(relative, str) or not isinstance(target, str) or
                    not link.is_symlink() or os.readlink(link) != target or
                    not Path(target).is_relative_to(local)):
                return False
        selected = manifest.get("selected_sha256")
        if not isinstance(selected, dict):
            return False
        files = sorted(path for path in local.rglob("*")
                       if path.is_file() or path.is_symlink())
        tree = hashlib.sha256()
        actual_selected = {}
        total_bytes = 0
        selected_names = {
            "trace/streaming_trace_manifest.json", "trace/runtime_trace.jsonl",
            "trace/schedule.jsonl", "original-graph/summary.json",
            "stdout.log", "stderr.log",
        }
        for file in files:
            relative = file.relative_to(local).as_posix()
            if file.is_symlink():
                file_sha = hashlib.sha256(os.readlink(file).encode()).hexdigest()
                marker, size = b"L", file.lstat().st_size
            else:
                file_sha = sha(file)
                marker, size = b"F", file.stat().st_size
            tree.update(relative.encode() + b"\0" + marker +
                        bytes.fromhex(file_sha))
            total_bytes += size
            if relative in selected_names:
                actual_selected[relative] = file_sha
        if (manifest.get("tree_sha256") != tree.hexdigest() or
                manifest.get("file_count") != len(files) or
                manifest.get("total_bytes") != total_bytes or
                actual_selected != selected):
            return False
        for relative, selected_sha in selected.items():
            raw = local / relative
            observed = audit["trial_evidence_sha256"].get(str(raw))
            if observed is not None and observed != selected_sha:
                return False
        lineage_path = trial / "schedule-lineage.json"
        if lineage_path.is_file():
            lineage = obj(lineage_path)
            schedule = trial / "native-schedule.jsonl"
            if (lineage.get("durable_copy") != str(schedule) or
                    not schedule.is_file() or schedule.is_symlink() or
                    lineage.get("durable_copy_sha256") != sha(schedule) or
                    lineage.get("destination_sha256") != sha(schedule)):
                return False
    return True


def _frozen_source_cache_valid(cache: dict, fingerprint: dict,
                               config_root: Path, *,
                               require_local_attestation: bool = False) -> bool:
    """Recheck a sealed inspector's source and trial bytes before reuse."""
    try:
        audit_path = Path(cache["frozen_audit_path"])
        if (not audit_path.is_absolute() or audit_path.is_symlink() or
                sha(audit_path) != cache["frozen_audit_sha256"]):
            return False
        audit = obj(audit_path)
        binding = obj(config_root / f"{fingerprint['case_id']}.json")
        source = binding["campaign_python_source"]
        root = pinned_campaign_python(source)
        from .inspector_overlay import METHOD as OVERLAY_METHOD, verify_inspector_overlay
        overlay_pin = binding.get("inspector_overlay")
        if overlay_pin is None:
            overlay_valid = (audit.get("method") ==
                             "exact_frozen_python_full_native_inspect_case" and
                             "inspector_overlay" not in audit)
        else:
            overlay_valid = (audit.get("method") == OVERLAY_METHOD and
                             audit.get("inspector_overlay") ==
                             verify_inspector_overlay(source, root, overlay_pin))
        if (not overlay_valid or
                audit.get("fingerprint") != fingerprint or
                audit.get("row") != cache.get("row") or
                audit.get("source_root") != str(root.resolve()) or
                audit.get("source_tar_path") != source["source_tar_path"] or
                audit.get("source_tar_sha256") != source["source_tar_sha256"] or
                audit.get("inspector_sha256") != source["python_sha256"][
                    "Mallory/native_graphchecker_dispatch/checklist.py"] or
                Path(audit["engine_jar_path"]).is_symlink() or
                sha(Path(audit["engine_jar_path"])) != audit.get(
                    "engine_jar_sha256") or
                not isinstance(audit.get("trial_evidence_sha256"), dict) or
                not audit["trial_evidence_sha256"]):
            return False
        if "raw_archive_evidence" in audit:
            from .raw_archive import verify_trial_evidence
            if audit["raw_archive_evidence"] != binding.get("raw_archive_evidence"):
                return False
            return verify_trial_evidence(
                binding, fingerprint["case_id"],
                audit["trial_evidence_sha256"], audit.get("raw_summary_targets"))
        attestation = audit.get("local_artifact_attestation")
        if attestation is None:
            if require_local_attestation:
                return False
            return all(sha(Path(name)) == digest for name, digest in
                       audit["trial_evidence_sha256"].items())
        if not _local_artifact_attestation_valid(audit, fingerprint):
            return False
        return all(Path(name).is_file() and sha(Path(name)) == digest
                   for name, digest in audit["trial_evidence_sha256"].items())
    except (KeyError, OSError, ValueError, TypeError):
        return False


def _cached_terminal_inspection(item: dict, owner: str, config_root: Path,
                                state_root: Path, review: dict | None = None) -> dict:
    fingerprint = _terminal_fingerprint(item, config_root, state_root)
    if fingerprint is None:
        return inspect_case(item, owner, config_root, state_root, review)
    native_config_file, _ = _native_case_files(item, config_root, state_root)
    local_artifact_mode = bool(obj(native_config_file).get("runner", {}).get(
        "local_artifact_root"))
    if review is not None:
        fingerprint["review_sha256"] = hashlib.sha256(json.dumps(
            review, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    cache_path = _terminal_cache_path(state_root, item["case_id"])
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.with_suffix(".lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if cache_path.is_file():
            cache = obj(cache_path)
            pilot_path = Path(cache.get("pilot_receipt_path", ""))
            completed_path = Path(cache.get("completion_receipt_path", ""))
            basis = cache.get("basis")
            receipt_basis_valid = (
                basis not in ("pinned_pilot_and_completion_receipts",
                              "audited_promotion_receipt",
                              "frozen_source_full_native_inspect_case") or
                (completed_path.is_file() and
                 sha(completed_path) == cache.get("completion_receipt_sha256") and
                 (basis in ("audited_promotion_receipt",
                            "frozen_source_full_native_inspect_case") or
                  (pilot_path.is_file() and
                   sha(pilot_path) == cache.get("pilot_receipt_sha256")))))
            if basis == "frozen_source_full_native_inspect_case":
                receipt_basis_valid = (receipt_basis_valid and
                    _frozen_source_cache_valid(
                        cache, fingerprint, config_root,
                        require_local_attestation=local_artifact_mode))
            elif local_artifact_mode:
                # A prior full inspection on this host is not a remotely
                # verifiable cache until its frozen source and local raw
                # evidence are sealed in a host-identified receipt.
                receipt_basis_valid = False
            if (cache.get("fingerprint") == fingerprint and
                    cache.get("owner") == owner and
                    receipt_basis_valid and
                    cache.get("row", {}).get("terminal_disposition") in TERMINAL):
                return cache["row"]
        row = inspect_case(item, owner, config_root, state_root, review)
        if (row.get("terminal_disposition") in TERMINAL and
                _terminal_fingerprint(item, config_root, state_root) == fingerprint):
            atomic(cache_path, {"schema_version": 1, "owner": owner,
                                "basis": "full_native_inspect_case",
                                "fingerprint": fingerprint, "row": row})
        return row


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
    config_file, native_root = _native_case_files(item, config_root, state_root)
    if ((state_root / ".native-queue" / "invalid-overlap" /
         f"{case_id}.json").exists() or port_conflict_logs(native_root)):
        raise ValueError("native pilot contains a JUnit port collision")
    summary = native_root / "summary.json"
    entry = config_root / f"{case_id}.json"
    if (receipt.get("config_sha256") != sha(config_file) or
            receipt.get("summary_sha256") != sha(summary) or
            (entry != config_file and receipt.get("binding_sha256") != sha(entry))):
        raise ValueError("native pilot evidence changed")
    fingerprint = _terminal_fingerprint(item, config_root, state_root)
    if (fingerprint is None or
            fingerprint["config_sha256"] != receipt["config_sha256"] or
            fingerprint["summary_sha256"] != receipt["summary_sha256"]):
        raise ValueError("native pilot terminal checkpoint changed")
    completed_path = (state_root / ".native-queue" / "completions" /
                      f"{case_id}.json")
    if completed_path.is_file():
        completed = obj(completed_path)
        if (completed.get("case_id") != case_id or
                completed.get("method") != "original_native_graphchecker_campaign" or
                completed.get("native_tested_complete") is not True or
                completed.get("terminal_disposition") not in TERMINAL or
                completed.get("config_sha256") != fingerprint["config_sha256"] or
                completed.get("summary_sha256") != fingerprint["summary_sha256"] or
                completed.get("summary_path") != str(summary.resolve()) or
                (entry != config_file and completed.get("binding_sha256") !=
                 fingerprint["binding_sha256"])):
            raise ValueError("native pilot completion receipt changed")
        cache_path = _terminal_cache_path(state_root, case_id)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with cache_path.with_suffix(".lock").open("a+") as cache_lock:
            fcntl.flock(cache_lock, fcntl.LOCK_EX)
            expected_row = {key: completed[key] for key in (
                "terminal_disposition", "native_tested_complete", "fault_trials",
                "strict_fault_trials", "target_retained_fault_trials",
                "target_throw_trials", "candidate_trials", "elapsed_seconds")}
            if not cache_path.is_file():
                atomic(cache_path, {"schema_version": 1, "owner": owners[case_id],
                                    "basis": "pinned_pilot_and_completion_receipts",
                                    "pilot_receipt_path": str(path.resolve()),
                                    "pilot_receipt_sha256": sha(path),
                                    "completion_receipt_path": str(completed_path.resolve()),
                                    "completion_receipt_sha256": sha(completed_path),
                                    "fingerprint": fingerprint, "row": expected_row})
            else:
                cache = obj(cache_path)
                if (cache.get("schema_version") == 1 and
                        cache.get("basis") == "pinned_pilot_and_completion_receipts" and
                        cache.get("owner") == owners[case_id] and
                        cache.get("fingerprint") == fingerprint and
                        cache.get("pilot_receipt_path") == str(path.resolve()) and
                        cache.get("completion_receipt_path") == str(completed_path.resolve()) and
                        cache.get("completion_receipt_sha256") == sha(completed_path) and
                        cache.get("row") == expected_row and
                        cache.get("pilot_receipt_sha256") != sha(path)):
                    cache["pilot_receipt_sha256"] = sha(path)
                    atomic(cache_path, cache)
    row = _cached_terminal_inspection(item, owners[case_id], config_root,
                                      state_root)
    if row["native_tested_complete"] is not True:
        raise ValueError("native pilot is not an audited completed fuzz check")
    return receipt


def _pinned_engine_root(config_file: Path) -> Path:
    """Resolve the source-built engine recorded by this immutable weave."""
    config = obj(config_file)
    weave = obj(Path(config["native_weave_config"]))
    receipt = obj(Path(weave["output_classes"]) /
                  "native-original-weave-receipt.json")
    jar = Path(receipt["engine_jar"])
    if (not jar.is_absolute() or jar.is_symlink() or
            jar.name != "mallory-original-graphchecker-seed-1.0-SNAPSHOT.jar" or
            jar.parent.name != "target" or
            sha(jar) != receipt.get("engine_jar_sha256")):
        raise ValueError("native weave engine JAR pin changed")
    root = jar.parent.parent
    if root.is_symlink():
        raise ValueError("native engine root is a symlink")
    return root


def _pinned_campaign_command(config_file: Path, root: Path) -> list[str]:
    return [sys.executable, "-m", "Mallory.native_graphchecker_campaign",
            "--config", str(config_file), "--output", str(root)]


def pinned_campaign_python(source: dict[str, Any]) -> Path:
    """Verify the exact per-case campaign Python source before a resume."""
    root = Path(source.get("root_path", ""))
    archive = Path(source.get("source_tar_path", ""))
    expected = source.get("python_sha256")
    if (not root.is_absolute() or not root.is_dir() or root.is_symlink() or
            not archive.is_absolute() or not archive.is_file() or
            archive.is_symlink() or sha(archive) != source.get(
                "source_tar_sha256") or
            not isinstance(expected, dict) or not expected):
        raise ValueError("per-case campaign Python source pin is invalid")
    actual = {}
    for path in sorted(root.rglob("*.py")):
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("per-case campaign Python contains a symlink")
        actual[str(path.relative_to(root))] = sha(path)
    if actual != expected:
        raise ValueError("per-case campaign Python source changed")
    required = source.get("required_files_sha256", {})
    if not isinstance(required, dict):
        raise ValueError("per-case required source pins are invalid")
    for relative, expected_sha in required.items():
        if (not isinstance(relative, str) or
                not relative.startswith("Mallory/") or
                Path(relative).is_absolute() or ".." in Path(relative).parts):
            raise ValueError("per-case required source path is unsafe")
        path = root / relative
        if path.is_symlink() or not path.is_file() or sha(path) != expected_sha:
            raise ValueError("per-case required source changed")
    return root


def run_pinned_campaign(config_file: Path, root: Path) -> dict[str, Any]:
    """Resume one native campaign in a fresh Python process with its engine."""
    engine_root = _pinned_engine_root(config_file)
    env = os.environ.copy()
    env["MALLORY_NATIVE_ENGINE_ROOT"] = str(engine_root)
    campaign_source = env.get("MALLORY_NATIVE_CAMPAIGN_PYTHON_ROOT")
    result = subprocess.run(
        _pinned_campaign_command(config_file, root),
        cwd=Path(campaign_source) if campaign_source else
            Path(__file__).resolve().parents[2], env=env,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=True)
    return json.loads(result.stdout)


def _publish_results_if_requested(results_dir: Path | None, inventory: Path,
                                  ownership_file: Path, config_root: Path,
                                  state_root: Path,
                                  epoch_receipt: Path | None = None,
                                  epoch_receipt_sha256: str | None = None) -> None:
    if results_dir is not None:
        from .results import export_native_results
        export_native_results(inventory, ownership_file, config_root,
                              state_root, results_dir, epoch_receipt,
                              epoch_receipt_sha256)


def run_worker(*, host: str, slot: int, slots: int, inventory: Path,
               ownership_file: Path, config_root: Path, state_root: Path,
               scratch_root: Path, isolation_file: Path,
               results_dir: Path | None = None,
               reviews: Path | None = None, only_case: str | None = None,
               min_memory_gib: float = 12, min_state_gib: float = 2,
               min_scratch_gib: float = 4,
               epoch_receipt: Path | None = None,
               epoch_receipt_sha256: str | None = None,
               runner: Callable[[Path, Path], dict] = run_pinned_campaign) -> dict[str, Any]:
    physical_host(host)
    if not 1 <= slots <= MAX_SLOTS or not 0 <= slot < slots:
        raise ValueError("native queue supports one or two slots per host")
    cases, by_id, epoch = load_queue_inventory(
        inventory, state_root, epoch_receipt, epoch_receipt_sha256)
    require_epoch_results_dir(results_dir, state_root, epoch)
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
            config_file, root = _native_case_files(item, config_root, state_root)
            binding_file = config_root / f"{case_id}.json"
            if config_file == binding_file:
                binding_file = None
            row = _cached_terminal_inspection(item, host, config_root,
                                              state_root, reviewed.get(case_id))
            if row["terminal_disposition"] in TERMINAL:
                validate_isolation(profile, item["system"], case_id,
                                   obj(config_file),
                                   owners, host)
                # The copied v15 binding has the same bytes but a new path.
                # Reissuing a v14 receipt would change its binding_path.
                if epoch is None or case_id not in epoch["legacy_case_ids"]:
                    completion(item, row, config_file, state_root, queue_root,
                               native_root=root, binding_file=binding_file,
                               config_root=config_root)
                _publish_results_if_requested(results_dir, inventory,
                                              ownership_file, config_root,
                                              state_root, epoch_receipt,
                                              epoch_receipt_sha256)
                continue
            if row["terminal_disposition"] not in ("ready", "resumable"):
                continue
            if _campaign_running(root):
                continue
            root.mkdir(parents=True, exist_ok=True)
            with (root / ".dispatch.lock").open("a+") as case_lock:
                try:
                    fcntl.flock(case_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                row = _cached_terminal_inspection(item, host, config_root,
                                                  state_root, reviewed.get(case_id))
                if row["terminal_disposition"] not in ("ready", "resumable"):
                    continue
                if _campaign_running(root):
                    continue
                isolation = validate_isolation(profile, item["system"], case_id,
                                               obj(config_file), owners, host)
                _resources(root, scratch_root, min_memory_gib,
                           min_state_gib, min_scratch_gib)
                python_root = None
                if binding_file is not None:
                    python_source = obj(binding_file).get("campaign_python_source")
                    if python_source is not None:
                        if not isinstance(python_source, dict):
                            raise ValueError("per-case campaign Python pin is invalid")
                        python_root = pinned_campaign_python(python_source)
                scratch = scratch_root / case_id
                if scratch.is_symlink():
                    raise ValueError("case scratch path is a symlink")
                scratch.mkdir(exist_ok=True)
                attempt_file = (queue_root / "attempts" / case_id /
                                f"{time.time_ns()}-{os.getpid()}.json")
                attempt = {"schema_version": 1, "case_id": case_id,
                           "host": host, "slot": slot, "pid": os.getpid(),
                           "config_sha256": sha(config_file),
                           "binding_sha256": (sha(binding_file) if binding_file
                                              is not None else None),
                           "campaign_python_root": (str(python_root) if
                                                    python_root is not None else None),
                           "isolation_sha256": sha(isolation_file),
                           "port_policy": isolation,
                           "scratch_path": str(scratch.resolve()),
                           "state_path": str(root.resolve()),
                           "started_at": time.time(), "status": "running"}
                atomic(attempt_file, attempt)
                previous_tmpdir = os.environ.get("TMPDIR")
                previous_pythonpath = os.environ.get("PYTHONPATH")
                previous_campaign_source = os.environ.get(
                    "MALLORY_NATIVE_CAMPAIGN_PYTHON_ROOT")
                os.environ["TMPDIR"] = str(scratch.resolve())
                if python_root is not None:
                    os.environ["PYTHONPATH"] = str(python_root)
                    os.environ["MALLORY_NATIVE_CAMPAIGN_PYTHON_ROOT"] = str(
                        python_root)
                else:
                    os.environ.pop("MALLORY_NATIVE_CAMPAIGN_PYTHON_ROOT", None)
                try:
                    runner(config_file, root)
                    after = _cached_terminal_inspection(
                        item, host, config_root, state_root,
                        reviewed.get(case_id))
                    if sha(isolation_file) != attempt["isolation_sha256"]:
                        raise ValueError("native isolation profile changed during campaign")
                    validate_isolation(profile, item["system"], case_id,
                                       obj(config_file), owners, host)
                    if after["terminal_disposition"] not in TERMINAL:
                        raise RuntimeError("native campaign returned without audited terminal result")
                    result = completion(item, after, config_file, state_root,
                                        queue_root, native_root=root,
                                        binding_file=binding_file,
                                        config_root=config_root)
                    _publish_results_if_requested(results_dir, inventory,
                                                  ownership_file, config_root,
                                                  state_root, epoch_receipt,
                                                  epoch_receipt_sha256)
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
                    if previous_pythonpath is None:
                        os.environ.pop("PYTHONPATH", None)
                    else:
                        os.environ["PYTHONPATH"] = previous_pythonpath
                    if previous_campaign_source is None:
                        os.environ.pop("MALLORY_NATIVE_CAMPAIGN_PYTHON_ROOT", None)
                    else:
                        os.environ["MALLORY_NATIVE_CAMPAIGN_PYTHON_ROOT"] = (
                            previous_campaign_source)
    return {"host": host, "slot": slot, "completed": len(results),
            "cases": [row["case_id"] for row in results]}


def run_host(*, host: str, slots: int, pilot: Path, inventory: Path,
             ownership_file: Path, config_root: Path, state_root: Path,
             scratch_root: Path, isolation_file: Path,
             results_dir: Path | None = None,
             reviews: Path | None = None,
             min_memory_gib: float = 12, min_state_gib: float = 2,
             min_scratch_gib: float = 4,
             epoch_receipt: Path | None = None,
             epoch_receipt_sha256: str | None = None) -> list[int]:
    physical_host(host)
    if not 1 <= slots <= MAX_SLOTS:
        raise ValueError("native queue supports at most two slots per host")
    cases, by_id, epoch = load_queue_inventory(
        inventory, state_root, epoch_receipt, epoch_receipt_sha256)
    require_epoch_results_dir(results_dir, state_root, epoch)
    owners = load_ownership(ownership_file, set(by_id))
    pilot_receipt(pilot, inventory, ownership_file, config_root, state_root,
                  cases, owners, isolation_file)
    profile = obj(isolation_file)
    for item in cases:
        case_id = item["case_id"]
        if owners[case_id] != host:
            continue
        row = _cached_terminal_inspection(item, host, config_root, state_root)
        if row["terminal_disposition"] not in ("ready", "resumable"):
            continue
        config_file, _ = _native_case_files(item, config_root, state_root)
        validate_isolation(profile, item["system"], case_id,
                           obj(config_file), owners, host)
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
        if results_dir is not None:
            argv.extend(("--results-dir", str(results_dir)))
        if epoch_receipt is not None:
            argv.extend(("--inventory-epoch-receipt", str(epoch_receipt),
                         "--inventory-epoch-sha256", epoch_receipt_sha256))
        argv.extend(("--pilot-receipt", str(pilot)))
        processes.append(subprocess.Popen(argv,
                                          cwd=Path(__file__).resolve().parents[2]))
    controller = (state_root / ".native-queue" / "controllers" /
                  f"{host}.json")
    status = {"schema_version": 1, "host": host, "slots": slots,
              "controller_pid": os.getpid(),
              "worker_pids": [process.pid for process in processes],
              "started_at": time.time(), "status": "running"}
    atomic(controller, status)
    codes = [process.wait() for process in processes]
    status.update(status="finished", ended_at=time.time(),
                  worker_exit_codes=codes)
    atomic(controller, status)
    return codes
