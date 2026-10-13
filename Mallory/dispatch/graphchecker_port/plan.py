"""Print a read-only three-node plan; this module cannot launch campaigns.

Only a terminal *core checkpoint* with its result receipt skips a case. Legacy
Mallory tables are deliberately not used as completion authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

SYSTEM_WAVES = (
    {"node0": "hdfs", "node1": "hbase", "node2": "solr"},
    {"node0": "zookeeper"},
)
CASE_ID = re.compile(r"^(HDFS|HBASE|SOLR|ZOOKEEPER)-[0-9]{2}$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checkpoint_state(case_id: str, state_root: Path) -> tuple[str, dict]:
    """Fail closed on an unfamiliar checkpoint; never re-run a terminal one."""
    checkpoint = state_root / case_id / "checkpoint.json"
    if not checkpoint.exists():
        return "fresh", {"checkpoint": str(checkpoint)}
    try:
        row = json.loads(checkpoint.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "blocked_invalid_checkpoint", {"checkpoint": str(checkpoint)}
    if (not isinstance(row, dict) or row.get("schema_version") != 1
            or row.get("case_id") != case_id
            or not isinstance(row.get("config_sha256"), str)):
        return "blocked_invalid_checkpoint", {"checkpoint": str(checkpoint)}
    evidence = {"checkpoint": str(checkpoint),
                "checkpoint_config_sha256": row["config_sha256"]}
    terminal = row.get("terminal")
    if terminal is True:
        if not isinstance(row.get("status"), str) or row["status"] == "running":
            return "blocked_unknown_checkpoint_schema", evidence
        summary = state_root / case_id / "summary.json"
        evidence["summary"] = str(summary)
        try:
            result = json.loads(summary.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return "blocked_terminal_without_summary", evidence
        if (not isinstance(result, dict) or result.get("case_id") != case_id
                or result.get("config_sha256") != row["config_sha256"]
                or result.get("status") != row["status"]
                or result.get("terminal") is not True):
            return "blocked_terminal_summary_mismatch", evidence
        return "terminal", evidence
    if terminal is False and row.get("status") == "running":
        return "resumable", evidence
    return "blocked_unknown_checkpoint_schema", evidence


def build_plan(inventory: Path, config_root: Path, state_root: Path,
               snapshot_receipt: Path | None = None) -> dict:
    document = json.loads(inventory.read_text(encoding="utf-8"))
    cases = document.get("cases")
    if not isinstance(cases, list) or len(cases) != 102:
        raise ValueError("expected the exact 102-check inventory")
    receipt = None
    if snapshot_receipt is not None:
        receipt = json.loads(snapshot_receipt.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict) or receipt.get("schema_version") != 1:
            raise ValueError("snapshot receipt must use schema 1")
    ownership = {system: (wave, host)
                 for wave, hosts in enumerate(SYSTEM_WAVES)
                 for host, system in hosts.items()}
    result = []
    seen = set()
    for item in cases:
        case_id = item.get("case_id")
        system = item.get("system")
        if not isinstance(case_id, str) or not CASE_ID.fullmatch(case_id) or (
                system not in ownership or case_id.split("-", 1)[0].lower() != system
                or case_id in seen):
            raise ValueError(f"invalid or repeated inventory case: {case_id}")
        seen.add(case_id)
        wave, host = ownership[system]
        config = config_root / (case_id + ".json")
        state, evidence = checkpoint_state(case_id, state_root)
        config_digest = sha256(config) if config.is_file() else None
        if (state == "resumable" and config_digest is not None
                and evidence.get("checkpoint_config_sha256") != config_digest):
            state = "blocked_config_changed"
        row = {"case_id": case_id, "system": system, "wave": wave,
               "host": host, "checkpoint_state": state,
               "evidence_paths": evidence,
               "config": str(config), "config_sha256": config_digest}
        row["dispatch_state"] = (
            "skip_terminal" if state == "terminal" else
            "blocked_checkpoint" if state.startswith("blocked_") else
            "waiting_config" if not config.is_file() else
            "waiting_snapshots" if receipt is None else
            "release_review_required")
        result.append(row)
    return {"schema_version": 1, "mode": "read_only_plan",
            "inventory": str(inventory), "inventory_sha256": sha256(inventory),
            "snapshot_receipt": str(snapshot_receipt) if snapshot_receipt else None,
            "snapshot_receipt_sha256": sha256(snapshot_receipt)
            if snapshot_receipt else None,
            "max_concurrent_jobs": 3, "max_jobs_per_host": 1,
            "waves": SYSTEM_WAVES, "cases": result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path,
                        default=Path("Mallory/cases/inventory.json"))
    parser.add_argument("--config-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--snapshot-receipt", type=Path)
    args = parser.parse_args()
    print(json.dumps(build_plan(args.inventory, args.config_root,
                                args.state_root, args.snapshot_receipt),
                     sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
