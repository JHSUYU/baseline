"""Explicit v15 correction over the immutable v14 native queue inventory."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from Mallory.native_graphchecker_dispatch.checklist import load_inventory


BASE_SHA256 = "4966dae655433f56caee39298120fd87d28def86e934fe7d7d2115eaf340d924"
EFFECTIVE_SHA256 = "6ed7d0799016a295a28d318dfc0e2f4bd55a7817042bd540104b28a374aef881"
CASE_ID = "HDFS-40"
FIELD = "target.runtime_mapping.check_sites[0]"
LEGACY_CASE_IDS = frozenset({
    "HBASE-01", "HBASE-02", "HDFS-11", "HDFS-14", "HDFS-28", "HDFS-29",
    "HDFS-30", "HDFS-31", "SOLR-01", "SOLR-05", "SOLR-07", "SOLR-09",
    "SOLR-19", "ZOOKEEPER-01", "ZOOKEEPER-02", "ZOOKEEPER-03",
    "ZOOKEEPER-05", "ZOOKEEPER-07",
})


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _row_sha(row: dict) -> str:
    return hashlib.sha256(json.dumps(row, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def freeze_epoch_receipt(inventory: Path, state_root: Path,
                         results_path: Path) -> dict[str, Any]:
    """Describe the complete v14 terminal set at the quiescent handoff.

    The caller holds the queue's host, promotion, and results locks. A later
    v14 completion therefore cannot be silently omitted from this snapshot.
    """
    if inventory.is_symlink() or _sha(inventory) != BASE_SHA256:
        raise ValueError("v15 base inventory differs from immutable v14 inventory")
    if results_path.is_symlink() or not results_path.is_file():
        raise ValueError("v14 results table is unavailable")
    cases, _ = load_inventory(inventory)
    by_id = {row["case_id"]: row for row in cases}
    original = by_id[CASE_ID]
    old_mapping = original["target"]["runtime_mapping"]["check_sites"]
    if len(old_mapping) != 1 or not old_mapping[0].endswith("@131:branch:12"):
        raise ValueError("v14 HDFS-40 guard identity changed")
    replacement = old_mapping[0].rsplit("@", 1)[0] + "@137:branch:14"
    new_row = copy.deepcopy(original)
    new_row["target"]["runtime_mapping"]["check_sites"] = [replacement]
    table = json.loads(results_path.read_text())
    if (table.get("schema_version") != 1 or
            table.get("inventory_sha256") != BASE_SHA256 or
            len(table.get("rows", [])) != 102):
        raise ValueError("v14 102-row results table identity changed")
    terminal_rows = {row["case_id"]: row for row in table["rows"]
                     if row.get("completion_receipt_sha256")}
    completed = state_root / ".native-queue" / "completions"
    receipt_paths = {path.stem: path for path in completed.glob("*.json")}
    if (not LEGACY_CASE_IDS.issubset(terminal_rows) or
            set(terminal_rows) != set(receipt_paths) or
            CASE_ID in receipt_paths or
            table.get("verified_terminal_count") != sum(
                row.get("native_state") == "verified_terminal"
                for row in table["rows"])):
        raise ValueError("v14 table and complete completion set disagree")
    legacy = []
    for case_id, path in sorted(receipt_paths.items()):
        if (path.is_symlink() or case_id not in by_id or
                terminal_rows[case_id].get("completion_receipt_sha256") != _sha(path)):
            raise ValueError(f"v14 completion/table SHA mismatch: {case_id}")
        legacy.append({"case_id": case_id,
                       "inventory_row_sha256": _row_sha(by_id[case_id]),
                       "completion_receipt_sha256": _sha(path)})
    return {"schema_version": 1, "epoch": "native-102-v15-hdfs40",
            "base_inventory_sha256": BASE_SHA256,
            "effective_inventory_sha256": EFFECTIVE_SHA256,
            "v14_results_table_sha256": _sha(results_path),
            "amended_case_id": CASE_ID, "changed_field": FIELD,
            "old_mapping": old_mapping[0], "new_mapping": replacement,
            "old_row_sha256": _row_sha(original),
            "new_row_sha256": _row_sha(new_row),
            "legacy_terminal_count": len(legacy),
            "legacy_completions": legacy}


def require_epoch_results_dir(results_dir: Path | None, state_root: Path,
                              epoch: dict[str, Any] | None) -> None:
    """Reject a v14 result destination before a v15 campaign can start."""
    if epoch is None or results_dir is None:
        return
    if results_dir.resolve() == (state_root.parent / "results").resolve():
        raise ValueError("v15 results cannot overwrite the v14 result table")
    previous = results_dir / "native-102-results.json"
    if previous.is_file() and json.loads(previous.read_text()).get(
            "inventory_epoch") != epoch:
        raise ValueError("v15 results directory contains another inventory epoch")


def load_queue_inventory(inventory: Path, state_root: Path,
                         epoch_receipt: Path | None = None,
                         epoch_receipt_sha256: str | None = None
                         ) -> tuple[list[dict], dict[str, str], dict[str, Any] | None]:
    """Return effective rows while retaining the base file for v14 pilot pins.

    The opt-in receipt permits exactly one source-backed HDFS-40 mapping change.
    Completed v14 rows and receipts are checked, never rewritten.
    """
    if epoch_receipt is None and epoch_receipt_sha256 is None:
        cases, systems = load_inventory(inventory)
        return cases, systems, None
    if (epoch_receipt is None or epoch_receipt_sha256 is None or
            not epoch_receipt.is_absolute() or epoch_receipt.is_symlink() or
            not epoch_receipt.is_file() or
            _sha(epoch_receipt) != epoch_receipt_sha256):
        raise ValueError("v15 epoch receipt requires its exact SHA-256 pin")
    if inventory.is_symlink() or _sha(inventory) != BASE_SHA256:
        raise ValueError("v15 base inventory differs from immutable v14 inventory")
    cases, systems = load_inventory(inventory)
    receipt = json.loads(epoch_receipt.read_text())
    if (receipt.get("schema_version") != 1 or
            receipt.get("epoch") != "native-102-v15-hdfs40" or
            receipt.get("base_inventory_sha256") != BASE_SHA256 or
            receipt.get("effective_inventory_sha256") != EFFECTIVE_SHA256 or
            receipt.get("amended_case_id") != CASE_ID or
            receipt.get("changed_field") != FIELD):
        raise ValueError("v15 correction receipt identity changed")
    by_id = {row["case_id"]: row for row in cases}
    original = by_id[CASE_ID]
    old_mapping = original["target"]["runtime_mapping"]["check_sites"]
    replacement = receipt.get("new_mapping")
    if (len(old_mapping) != 1 or old_mapping[0] != receipt.get("old_mapping") or
            not old_mapping[0].endswith("@131:branch:12") or
            not isinstance(replacement, str) or
            replacement != old_mapping[0].rsplit("@", 1)[0] + "@137:branch:14" or
            _row_sha(original) != receipt.get("old_row_sha256")):
        raise ValueError("v15 correction is not the exact HDFS-40 guard change")
    effective = copy.deepcopy(cases)
    new_row = next(row for row in effective if row["case_id"] == CASE_ID)
    new_row["target"]["runtime_mapping"]["check_sites"] = [replacement]
    if (_row_sha(new_row) != receipt.get("new_row_sha256") or
            new_row["target"]["site_id"] != original["target"]["site_id"] or
            new_row["workload"] != original["workload"]):
        raise ValueError("v15 corrected row changed another identity")
    document = json.loads(inventory.read_text())
    for index, row in enumerate(document["cases"]):
        if row["case_id"] == CASE_ID:
            document["cases"][index] = new_row
            break
    encoded = (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode()
    if hashlib.sha256(encoded).hexdigest() != EFFECTIVE_SHA256:
        raise ValueError("v15 corrected full-inventory SHA-256 changed")
    legacy = receipt.get("legacy_completions")
    legacy_ids = {entry.get("case_id") for entry in legacy
                  if isinstance(entry, dict)} if isinstance(legacy, list) else set()
    if (not isinstance(legacy, list) or len(legacy) != len(legacy_ids) or
            len(legacy) != receipt.get("legacy_terminal_count") or
            not LEGACY_CASE_IDS.issubset(legacy_ids) or CASE_ID in legacy_ids):
        raise ValueError("v15 receipt must pin the complete v14 terminal set")
    old_table = state_root.parent / "results" / "native-102-results.json"
    if (not old_table.is_file() or old_table.is_symlink() or
            _sha(old_table) != receipt.get("v14_results_table_sha256")):
        raise ValueError("v15 v14 results table pin changed")
    current_completions = {path.stem for path in (state_root / ".native-queue" /
                                                 "completions").glob("*.json")}
    if not legacy_ids.issubset(current_completions):
        raise ValueError("v15 legacy completion set changed")
    for entry in legacy:
        if not isinstance(entry, dict):
            raise ValueError("v15 legacy completion entry is invalid")
        case_id = entry.get("case_id")
        if (case_id == CASE_ID or case_id not in by_id or
                _row_sha(by_id[case_id]) != entry.get("inventory_row_sha256") or
                _row_sha(next(row for row in effective if row["case_id"] == case_id))
                != entry.get("inventory_row_sha256")):
            raise ValueError("v15 changed a completed v14 inventory row")
        path = (state_root / ".native-queue" / "completions" /
                f"{case_id}.json")
        if (path.is_symlink() or not path.is_file() or
                _sha(path) != entry.get("completion_receipt_sha256")):
            raise ValueError(f"v15 legacy completion pin changed: {case_id}")
        completed = json.loads(path.read_text())
        if (completed.get("case_id") != case_id or
                completed.get("method") != "original_native_graphchecker_campaign" or
                completed.get("native_tested_complete") is not True):
            raise ValueError(f"v15 legacy completion invalid: {case_id}")
    metadata = {"epoch": receipt["epoch"],
                "base_inventory_sha256": BASE_SHA256,
                "effective_inventory_sha256": EFFECTIVE_SHA256,
                "epoch_receipt_sha256": epoch_receipt_sha256,
                "amended_case_id": CASE_ID,
                "old_row_sha256": receipt["old_row_sha256"],
                "new_row_sha256": receipt["new_row_sha256"],
                "legacy_terminal_count": len(legacy),
                "legacy_case_ids": sorted(legacy_ids),
                "v14_results_table_sha256": receipt["v14_results_table_sha256"]}
    return effective, systems, metadata
