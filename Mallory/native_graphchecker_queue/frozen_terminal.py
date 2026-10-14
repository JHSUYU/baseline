"""Audit a sealed campaign with the Python source that actually ran it.

Graph summary schemas can change after a campaign is sealed.  This module
executes the pinned, archived inspector in a separate process and records the
exact source and trial files used by that inspection.  It never launches JUnit.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from Mallory.native_graphchecker_dispatch.checklist import (
    _native_case_files, _verify_alternate_junit,
)
from .queue import (_pinned_engine_root, _terminal_fingerprint, atomic, obj,
                    pinned_campaign_python, sha)
from .raw_archive import pinned_archives, verify_trial_evidence


_INSPECT = """
import json, sys
from pathlib import Path
from Mallory.native_graphchecker_dispatch.checklist import inspect_case
request = json.load(sys.stdin)
row = inspect_case(request['item'], request['owner'],
                   Path(request['config_root']), Path(request['state_root']))
print(json.dumps(row, sort_keys=True))
"""


def _project_binding(item: dict, entry: Path, native_config: dict) -> dict:
    """Remove only a later shared-source field unknown to older inspectors."""
    binding = copy.deepcopy(obj(entry))
    alternate = binding.get("alternate_original_junit")
    if alternate is None:
        return binding
    if not isinstance(alternate, dict):
        raise ValueError("invalid alternate JUnit binding")
    old_keys = {"attestation_path", "attestation_sha256"}
    shared_keys = {"shared_source_receipt_path", "shared_source_receipt_sha256"}
    if set(alternate) == old_keys | shared_keys:
        # The current verifier validates the shared copy, exact bytes and
        # unchanged original selector before the old inspector sees its v1 view.
        _verify_alternate_junit(item, entry, native_config)
        binding["alternate_original_junit"] = {
            key: alternate[key] for key in sorted(old_keys)}
    elif set(alternate) != old_keys:
        raise ValueError("unknown alternate JUnit binding fields")
    return binding


def _trial_sha256(root: Path, count: int) -> tuple[dict[str, str], dict[str, str]]:
    evidence: dict[str, str] = {}
    raw_targets: dict[str, str] = {}
    for index in range(count + 1):
        trial = root / "trials" / f"r{index:04d}"
        result = trial / "result.json"
        if not result.is_file():
            raise ValueError(f"missing sealed trial result: {result}")
        for relative in ("result.json", "native-summary.json",
                         "iteration-native/fault-events.jsonl",
                         "original-graph/summary.json"):
            path = trial / relative
            if path.is_file():
                name = str(path.absolute())
                evidence[name] = sha(path)
                if relative == "original-graph/summary.json" and path.parent.is_symlink():
                    raw_targets[name] = str(path.parent.readlink() / path.name)
    if len(list((root / "trials").glob("r*/result.json"))) != count + 1:
        raise ValueError("sealed campaign has extra trial results")
    return evidence, raw_targets


def _local_artifact_receipts(root: Path, count: int,
                             config: dict) -> dict[str, Any] | None:
    """Attest local raw bytes only on their physical owner host.

    This runs after the frozen inspector has recomputed each graph from raw
    trace bytes. The durable result and manifest bind those bytes for a later
    owner-host queue recheck. A different host cannot promote local raw data.
    """
    configured = config.get("runner", {}).get("local_artifact_root")
    if configured is None:
        return None
    local_root = Path(configured).resolve(strict=True)
    host = os.uname().nodename
    manifests: dict[str, str] = {}
    trees: dict[str, str] = {}
    for index in range(count + 1):
        trial = root / "trials" / f"r{index:04d}"
        path = trial / "local-artifacts.json"
        result = obj(trial / "result.json")
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"missing durable local artifact manifest: {path}")
        manifest_sha = sha(path)
        manifest = obj(path)
        local = Path(manifest.get("local_attempt_dir", ""))
        if (result.get("local_artifacts_manifest_sha256") != manifest_sha or
                manifest.get("schema_version") != 1 or
                manifest.get("status") != "closed" or
                manifest.get("host") != host or
                manifest.get("trial") != trial.name or
                manifest.get("campaign_root") != str(root.resolve()) or
                not local.is_absolute() or
                not local.resolve(strict=True).is_relative_to(local_root) or
                not local.is_dir()):
            raise ValueError(f"local raw artifact identity changed: {trial}")
        links = manifest.get("links")
        if not isinstance(links, dict) or not links:
            raise ValueError(f"local raw artifact links missing: {trial}")
        for relative, target in links.items():
            if (not isinstance(relative, str) or not isinstance(target, str) or
                    not (trial / relative).is_symlink() or
                    os.readlink(trial / relative) != target or
                    not Path(target).is_relative_to(local)):
                raise ValueError(f"local raw artifact link changed: {trial}/{relative}")
        files = sorted(path for path in local.rglob("*")
                       if path.is_file() or path.is_symlink())
        digest = hashlib.sha256()
        selected = {}
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
            digest.update(relative.encode() + b"\0" + marker +
                          bytes.fromhex(file_sha))
            total_bytes += size
            if relative in selected_names:
                selected[relative] = file_sha
        if (manifest.get("file_count") != len(files) or
                manifest.get("total_bytes") != total_bytes or
                manifest.get("tree_sha256") != digest.hexdigest() or
                manifest.get("selected_sha256") != selected):
            raise ValueError(f"local raw artifact bytes changed: {trial}")
        lineage = trial / "schedule-lineage.json"
        if lineage.is_file():
            schedule = obj(lineage)
            durable = trial / "native-schedule.jsonl"
            if (schedule.get("durable_copy") != str(durable) or
                    schedule.get("durable_copy_sha256") != sha(durable) or
                    schedule["durable_copy_sha256"] != schedule.get(
                        "destination_sha256")):
                raise ValueError(f"durable schedule lineage changed: {trial}")
        manifests[str(path)] = manifest_sha
        trees[trial.name] = digest.hexdigest()
    return {"host": host, "local_root": str(local_root),
            "manifest_sha256": manifests, "trial_tree_sha256": trees}


def inspect_frozen_terminal(item: dict, owner: str, config_root: Path,
                            state_root: Path) -> dict[str, Any]:
    """Return a source-pinned audit receipt; reject an incomplete campaign."""
    case_id = item["case_id"]
    entry = config_root / f"{case_id}.json"
    binding = obj(entry)
    source = binding.get("campaign_python_source")
    if not isinstance(source, dict):
        raise ValueError("terminal campaign lacks frozen Python source")
    inspector_key = "Mallory/native_graphchecker_dispatch/checklist.py"
    if inspector_key not in source.get("python_sha256", {}):
        raise ValueError("frozen source lacks original native inspector")
    python_root = pinned_campaign_python(source)
    config_file, native_root = _native_case_files(item, config_root, state_root)
    engine_root = _pinned_engine_root(config_file)
    fingerprint = _terminal_fingerprint(item, config_root, state_root)
    if fingerprint is None:
        raise ValueError("native checkpoint and summary are not terminal")
    native_config = obj(config_file)
    projected = _project_binding(item, entry, native_config)
    with tempfile.TemporaryDirectory(prefix=f"{case_id}-frozen-inspect-") as temp:
        projected_path = Path(temp) / f"{case_id}.json"
        projected_path.write_text(json.dumps(projected, sort_keys=True) + "\n")
        projected_sha = sha(projected_path)
        environment = os.environ.copy()
        environment.update(PYTHONPATH=str(python_root),
                           MALLORY_NATIVE_ENGINE_ROOT=str(engine_root),
                           PYTHONDONTWRITEBYTECODE="1")
        command = [sys.executable, "-c", _INSPECT]
        proc = subprocess.run(command, input=json.dumps({
            "item": item, "owner": owner, "config_root": temp,
            "state_root": str(state_root)}), text=True, capture_output=True,
            cwd=temp, env=environment, timeout=3600, check=True)
        row = json.loads(proc.stdout)
    if (row.get("native_tested_complete") is not True or
            row.get("terminal_disposition") not in (
                "tested_candidate", "tested_no_target_throw") or
            row.get("case_id") != case_id or row.get("owner") != owner or
            row.get("native_config") != str(config_file.resolve())):
        raise ValueError("frozen inspector did not verify this terminal case")
    summary = obj(native_root / "summary.json")
    if (row.get("fault_trials") != summary.get("completed_fault_trials") or
            row.get("elapsed_seconds") != summary.get("elapsed_seconds")):
        raise ValueError("frozen inspection differs from sealed summary")
    trial_hashes, raw_targets = _trial_sha256(native_root, row["fault_trials"])
    raw_pin = binding.get("raw_archive_evidence")
    if raw_pin is not None:
        pinned_archives(binding, case_id)
        if not verify_trial_evidence(binding, case_id, trial_hashes, raw_targets):
            raise ValueError("frozen raw archive differs from inspected trial evidence")
    local_artifacts = None if raw_pin is not None else _local_artifact_receipts(
        native_root, row["fault_trials"], native_config)
    if _terminal_fingerprint(item, config_root, state_root) != fingerprint:
        raise ValueError("terminal inputs changed during frozen inspection")
    jar = engine_root / "target/mallory-original-graphchecker-seed-1.0-SNAPSHOT.jar"
    receipt = {"schema_version": 1,
            "method": "exact_frozen_python_full_native_inspect_case",
            "case_id": case_id, "owner": owner,
            "fingerprint": fingerprint,
            "source_root": str(python_root.resolve()),
            "source_tar_path": source["source_tar_path"],
            "source_tar_sha256": source["source_tar_sha256"],
            "inspector_sha256": source["python_sha256"][inspector_key],
            "engine_jar_path": str(jar.resolve()),
            "engine_jar_sha256": sha(jar),
            "projected_binding_sha256": projected_sha,
            "trial_evidence_sha256": trial_hashes,
            "row": row}
    if local_artifacts is not None:
        receipt["local_artifact_attestation"] = local_artifacts
    if raw_pin is not None:
        receipt["raw_archive_evidence"] = raw_pin
        receipt["raw_summary_targets"] = raw_targets
    return receipt


def publish_frozen_terminal(item: dict, owner: str, config_root: Path,
                            state_root: Path, evidence_root: Path) -> Path:
    """Write the audit atomically after full read-only frozen inspection."""
    receipt = inspect_frozen_terminal(item, owner, config_root, state_root)
    destination = evidence_root / f"{item['case_id']}-frozen-terminal-audit.json"
    if destination.is_file() and obj(destination) != receipt:
        raise ValueError("existing frozen terminal audit differs")
    atomic(destination, receipt)
    return destination
