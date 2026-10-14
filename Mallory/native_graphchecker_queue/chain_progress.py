"""Publish audited bounded-chain progress without granting case completion.

The pointer is optional.  It pins an immutable ``inspect_chain`` receipt and
the manifest that produced it; the result exporter rechecks both against the
current verifier and all frozen segment evidence.  Formal completion still
requires the queue's separate full terminal adoption path.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from Mallory.native_graphchecker_dispatch.checklist import (
    _verify_alternate_junit,
)

from .chain_completion import inspect_chain
from .inventory_epoch import _row_sha, load_queue_inventory
from .queue import atomic, obj, sha


def _pinned(value: dict[str, str], label: str) -> Path:
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise ValueError(f"{label} needs exact path and SHA-256")
    path = Path(value["path"])
    if (not path.is_absolute() or path.is_symlink() or not path.is_file() or
            sha(path) != value["sha256"]):
        raise ValueError(f"{label} changed")
    return path


def _executed_junit(item: dict[str, Any], config: dict[str, Any],
                    pin: dict[str, Any]) -> str:
    junit = config.get("junit", {})
    executed = junit.get("class", "") + "#" + junit.get("method", "")
    selected = item["workload"].get("selected_selector")
    if executed == selected:
        if pin.get("alternate_attestation") is not None or pin.get(
                "alternate_source_receipt") is not None:
            raise ValueError("selected JUnit cannot borrow an alternate attestation")
        return executed
    attestation = _pinned(pin.get("alternate_attestation"),
                          "alternate original JUnit attestation")
    entry = {"mode": "native_region_state_case_binding",
             "alternate_original_junit": {
                 "attestation_path": str(attestation),
                 "attestation_sha256": sha(attestation)}}
    if pin.get("alternate_source_receipt") is not None:
        shared = _pinned(pin["alternate_source_receipt"],
                         "alternate shared source receipt")
        entry["alternate_original_junit"].update({
            "shared_source_receipt_path": str(shared),
            "shared_source_receipt_sha256": sha(shared)})
    with tempfile.TemporaryDirectory() as temp:
        binding = Path(temp) / "alternate-binding.json"
        binding.write_text(json.dumps(entry) + "\n")
        _verify_alternate_junit(item, binding, config)
    return executed


def validate_progress(item: dict[str, Any], pin_path: Path) -> dict[str, Any]:
    """Reinspect every pinned segment; return progress only while partial."""
    if pin_path.is_symlink() or not pin_path.is_file():
        raise ValueError("chain progress pointer changed")
    pin = obj(pin_path)
    expected = {"schema_version", "case_id", "inventory_row_sha256",
                "manifest", "receipt", "alternate_attestation",
                "alternate_source_receipt"}
    if (set(pin) != expected or pin["schema_version"] != 1 or
            pin["case_id"] != item["case_id"] or
            pin["inventory_row_sha256"] != _row_sha(item)):
        raise ValueError("chain progress identity changed")
    manifest_path = _pinned(pin["manifest"], "chain manifest")
    receipt_path = _pinned(pin["receipt"], "chain inspection receipt")
    receipt = obj(receipt_path)
    current = inspect_chain(manifest_path)
    if receipt != current:
        raise ValueError("chain inspection receipt differs from frozen inputs")
    if (receipt.get("case_id") != item["case_id"] or
            receipt.get("status") != "partial" or
            receipt.get("native_tested_complete") is not False or
            not receipt.get("formal_budget_authority_sha256") or
            not isinstance(receipt.get("completed_fault_trials"), int) or
            receipt["completed_fault_trials"] < 1 or
            receipt.get("distinct_fault_plan_keys") != receipt[
                "completed_fault_trials"]):
        raise ValueError("chain progress lacks partial formal authority")
    manifest = obj(manifest_path)
    first_config = _pinned(manifest["segments"][0]["config"],
                           "first segment config")
    config = obj(first_config)
    target = item["target"]
    if config.get("target_throw") != {
            "siteId": target["site_id"],
            "exceptionClass": target.get("target_exception")}:
        raise ValueError("chain progress target differs from inventory")
    executed = _executed_junit(item, config, pin)
    return {"status": "partial", "executed_original_junit": executed,
            "completed_fault_trials": receipt["completed_fault_trials"],
            "distinct_fault_plan_keys": receipt["distinct_fault_plan_keys"],
            "strict_fault_trials": receipt["strict_fault_trials"],
            "strict_target_retained_fault_trials": receipt[
                "strict_target_retained_fault_trials"],
            "strict_in_target_closure_trials": receipt[
                "strict_in_target_closure_trials"],
            "closure_attribution_basis": (
                "saved_result_flag; original_finalizer_join_requires_"
                "frozen_full_graph_audit"),
            "exact_target_throw_trials": receipt[
                "exact_target_throw_trials"],
            "elapsed_seconds": receipt["elapsed_seconds"],
            "formal_budget_authority_sha256": receipt[
                "formal_budget_authority_sha256"],
            "manifest_path": str(manifest_path),
            "manifest_sha256": sha(manifest_path),
            "receipt_path": str(receipt_path),
            "receipt_sha256": sha(receipt_path),
            "pin_path": str(pin_path.resolve()),
            "pin_sha256": sha(pin_path)}


def publish_progress(*, item: dict[str, Any], manifest: Path,
                     state_root: Path, alternate_attestation: Path | None = None,
                     alternate_source_receipt: Path | None = None) -> dict[str, Any]:
    """Atomically advance an audited partial pointer under the queue lock."""
    if manifest.is_symlink() or not manifest.is_absolute():
        raise ValueError("chain manifest must be an absolute regular path")
    receipt = inspect_chain(manifest)
    if (receipt.get("status") != "partial" or
            receipt.get("native_tested_complete") is not False or
            not receipt.get("formal_budget_authority_sha256") or
            receipt.get("completed_fault_trials", 0) < 1 or
            receipt.get("distinct_fault_plan_keys") != receipt.get(
                "completed_fault_trials")):
        raise ValueError("chain progress needs distinct trials and formal partial authority")
    queue_root = state_root / ".native-queue"
    directory = queue_root / "chain-progress"
    pin_path = directory / f'{item["case_id"]}.json'
    receipt_bytes = (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode()
    receipt_digest = hashlib.sha256(receipt_bytes).hexdigest()
    receipt_path = (directory / "receipts" /
                    f'{item["case_id"]}-{receipt_digest}.json')
    pin = {"schema_version": 1, "case_id": item["case_id"],
           "inventory_row_sha256": _row_sha(item),
           "manifest": {"path": str(manifest), "sha256": sha(manifest)},
           "receipt": {"path": str(receipt_path), "sha256": None},
           "alternate_attestation": None,
           "alternate_source_receipt": None}
    for name, path in (("alternate_attestation", alternate_attestation),
                       ("alternate_source_receipt", alternate_source_receipt)):
        if path is not None:
            pin[name] = {"path": str(path), "sha256": sha(path)}
    directory.mkdir(parents=True, exist_ok=True)
    with (queue_root / "promotion.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (queue_root / "completions" / f'{item["case_id"]}.json').exists():
            raise ValueError("a completed case cannot publish partial progress")
        if pin_path.is_symlink() or receipt_path.is_symlink():
            raise ValueError("chain progress path cannot be a symlink")
        if receipt_path.exists() and sha(receipt_path) != receipt_digest:
            raise ValueError("immutable chain receipt content address changed")
        if receipt_path.exists() and obj(receipt_path) != receipt:
            raise ValueError("immutable chain receipt path has other bytes")
        if not receipt_path.exists():
            atomic(receipt_path, receipt)
        pin["receipt"]["sha256"] = sha(receipt_path)
        with tempfile.TemporaryDirectory(dir=directory,
                                         prefix=".chain-progress-candidate-") as temp:
            candidate = Path(temp) / f'{item["case_id"]}.json'
            atomic(candidate, pin)
            validate_progress(item, candidate)
        if pin_path.exists():
            old = validate_progress(item, pin_path)
            if old["completed_fault_trials"] > receipt.get(
                    "completed_fault_trials", -1):
                raise ValueError("chain progress cannot regress")
            if old["completed_fault_trials"] == receipt.get(
                    "completed_fault_trials") and obj(pin_path) != pin:
                raise ValueError("chain progress changed without more trials")
        if not pin_path.exists() or obj(pin_path) != pin:
            atomic(pin_path, pin)
        return validate_progress(item, pin_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--epoch-receipt", type=Path)
    parser.add_argument("--epoch-sha256")
    parser.add_argument("--alternate-attestation", type=Path)
    parser.add_argument("--alternate-source-receipt", type=Path)
    args = parser.parse_args()
    cases, _, _ = load_queue_inventory(args.inventory, args.state_root,
                                       args.epoch_receipt, args.epoch_sha256)
    item = next((row for row in cases if row["case_id"] == args.case_id), None)
    if item is None:
        raise ValueError("case is absent from canonical inventory")
    print(json.dumps(publish_progress(
        item=item, manifest=args.manifest, state_root=args.state_root,
        alternate_attestation=args.alternate_attestation,
        alternate_source_receipt=args.alternate_source_receipt), sort_keys=True,
        indent=2))


if __name__ == "__main__":
    main()
