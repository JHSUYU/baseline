"""Audit a sealed campaign with the Python source that actually ran it.

Graph summary schemas can change after a campaign is sealed.  This module
executes the pinned, archived inspector in a separate process and records the
exact source and trial files used by that inspection.  It never launches JUnit.
"""

from __future__ import annotations

import copy
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


def _trial_sha256(root: Path, count: int) -> dict[str, str]:
    evidence: dict[str, str] = {}
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
                evidence[str(path.resolve())] = sha(path)
    if len(list((root / "trials").glob("r*/result.json"))) != count + 1:
        raise ValueError("sealed campaign has extra trial results")
    return evidence


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
    trial_hashes = _trial_sha256(native_root, row["fault_trials"])
    if _terminal_fingerprint(item, config_root, state_root) != fingerprint:
        raise ValueError("terminal inputs changed during frozen inspection")
    jar = engine_root / "target/mallory-original-graphchecker-seed-1.0-SNAPSHOT.jar"
    return {"schema_version": 1,
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


def publish_frozen_terminal(item: dict, owner: str, config_root: Path,
                            state_root: Path, evidence_root: Path) -> Path:
    """Write the audit atomically after full read-only frozen inspection."""
    receipt = inspect_frozen_terminal(item, owner, config_root, state_root)
    destination = evidence_root / f"{item['case_id']}-frozen-terminal-audit.json"
    if destination.is_file() and obj(destination) != receipt:
        raise ValueError("existing frozen terminal audit differs")
    atomic(destination, receipt)
    return destination
