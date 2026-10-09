"""Promote terminal healthy seeds into an audited per-host campaign queue.

This runs on the case's owner host.  It never starts a JVM: a separate lane
worker may consume ready configs as soon as capacity opens, while healthy
calibration of other cases continues.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

try:
    from .core_release import verify as verify_core_release
    from .promote import promote
    from .worker import atomic_json
except ImportError:
    from core_release import verify as verify_core_release
    from promote import promote
    from worker import atomic_json


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def terminal_seed(calibration: Path, dispatch: Path, case_id: str) -> tuple[dict | None, str]:
    """Require a terminal scientific dispatch receipt before promotion."""
    try:
        result = json.loads((calibration / "result.json").read_text(encoding="utf-8"))
        receipt = json.loads((dispatch / "result.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "not_terminal"
    attempt = result.get("last_dispatch_attempt_id")
    if (result.get("case_id") != case_id or receipt.get("case_id") != case_id
            or not attempt or receipt.get("attempt_id") != attempt
            or not receipt.get("scientific_completed")
            or receipt.get("scientific_result_status") != result.get("status")
            or receipt.get("status") not in ("command_succeeded", "command_failed")
            or not (dispatch / "attempts" / attempt / "exit.json").is_file()):
        return None, "dispatch_receipt_mismatch"
    if result.get("status") != "calibration_complete":
        return result, "healthy_seed_" + str(result.get("status"))
    return result, "eligible_for_promotion"


def refresh(*, host: str, inventory_path: Path, source_reference_path: Path,
            config_template: str, data_root: Path, cohort: str,
            output: Path, promoted_root: Path,
            core_release_manifest: Path | None = None,
            exclude_cases: set[str] | None = None) -> dict:
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    reference = json.loads(source_reference_path.read_text(encoding="utf-8"))
    if reference.get("inventory_sha256") != sha256(inventory_path):
        raise ValueError("source reference is stale for inventory")
    owner = json.loads((Path(__file__).with_name("shards") / "ownership.json").read_text())
    release = verify_core_release(core_release_manifest) if core_release_manifest else None
    if release:
        from Mallory.core import audit as audit_module
        if Path(audit_module.__file__).resolve().parents[2] != core_release_manifest.parent.resolve():
            raise ValueError("campaign queue is not executing from the pinned core release")
    calibration_root = data_root / ("calibration_" + cohort if cohort else "calibration")
    dispatch_root = data_root / "dispatch" / (host + ("-" + cohort if cohort else "")) / "calibration/cases"
    rows = []
    for row in inventory["cases"]:
        case_id = row["case_id"]
        if owner["owner"].get(case_id) != host:
            continue
        eligibility = row.get("eligibility", {})
        entry = {"case_id": case_id, "state": None,
                 "inventory_eligibility": eligibility.get("state")}
        if case_id in (exclude_cases or set()):
            entry.update({"state": "held_externally", "reason": "active pilot or campaign"})
            rows.append(entry)
            continue
        if eligibility.get("may_dispatch_healthy_seed") is False:
            entry.update({"state": "source_or_workload_ineligible",
                          "reason": eligibility.get("state", "not_dispatchable"),
                          "mapping_gaps": eligibility.get("mapping_gaps", [])})
            rows.append(entry)
            continue
        config_path = Path(config_template.format(case_id=case_id)).resolve()
        if not config_path.is_file():
            entry.update({"state": "healthy_config_missing",
                          "reason": str(config_path)})
            rows.append(entry)
            continue
        calibration = calibration_root / case_id
        summary, state = terminal_seed(calibration, dispatch_root / case_id, case_id)
        if state == "not_terminal":
            entry.update({"state": "healthy_not_terminal"})
            rows.append(entry)
            continue
        entry.update({"calibration_status": summary.get("status") if summary else None,
                      "state": state})
        if state == "eligible_for_promotion":
            try:
                if not release:
                    raise ValueError("fixed core release is unpinned")
                from Mallory.core.audit import audit_campaign
                audit = audit_campaign(calibration, calibration / "offline-causal-audit.json")
                if not audit["report_gate_passed"]:
                    raise ValueError("fixed-core healthy causal replay failed")
                promoted = promote(config_path, calibration,
                                   promoted_root / f"{case_id}.json", row, reference)
                entry.update({"state": "ready", "promoted_config": str(promoted),
                              "promoted_sha256": sha256(promoted),
                              "core_release_id": release["release_id"],
                              "calibration_sha256": sha256(calibration / "result.json"),
                              "attempt_id": summary["last_dispatch_attempt_id"]})
            except (OSError, ValueError, KeyError, TypeError) as exc:
                entry.update({"state": "promotion_rejected", "reason": str(exc)[:240]})
        rows.append(entry)
    manifest = {"schema_version": 1, "host": host, "cohort": cohort,
                "inventory_sha256": sha256(inventory_path),
                "source_reference_sha256": sha256(source_reference_path),
                "cases": sorted(rows, key=lambda entry: entry["case_id"])}
    if not output.is_file() or json.loads(output.read_text(encoding="utf-8")) != manifest:
        atomic_json(output, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, choices=("node0", "node1", "node2"))
    parser.add_argument("--cohort", default="")
    parser.add_argument("--inventory", type=Path, default=Path("Mallory/cases/inventory.json"))
    parser.add_argument("--source-reference", type=Path,
                        default=Path("Mallory/dispatch/source_reference.json"))
    parser.add_argument("--case-config-template", default="Mallory/cases/{case_id}.json")
    parser.add_argument("--data-root", type=Path, default=Path("data/mallory"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--promoted-root", type=Path,
                        default=Path("data/mallory/promoted_configs"))
    parser.add_argument("--core-release-manifest", type=Path,
                        help="required to audit and promote healthy seeds")
    parser.add_argument("--exclude-case", action="append", default=[],
                        help="leave a live campaign's calibration and config untouched")
    parser.add_argument("--watch-seconds", type=float, default=0,
                        help="poll interval; 0 performs one refresh")
    args = parser.parse_args()
    if args.cohort and not args.cohort.isalnum():
        parser.error("cohort must be alphanumeric")
    if args.watch_seconds < 0:
        parser.error("watch interval must be nonnegative")
    output = args.output or (args.data_root / "dispatch" /
                             (args.host + ("-" + args.cohort if args.cohort else "")) /
                             "campaign_ready.json")
    while True:
        manifest = refresh(host=args.host, inventory_path=args.inventory,
                           source_reference_path=args.source_reference,
                           config_template=args.case_config_template,
                           data_root=args.data_root, cohort=args.cohort,
                           output=output, promoted_root=args.promoted_root,
                           core_release_manifest=args.core_release_manifest,
                           exclude_cases=set(args.exclude_case))
        ready = sum(row["state"] == "ready" for row in manifest["cases"])
        print(json.dumps({"host": args.host, "cohort": args.cohort,
                          "ready": ready, "terminal_seeds": len(manifest["cases"]),
                          "output": str(output)}, sort_keys=True), flush=True)
        if not args.watch_seconds:
            return 0
        time.sleep(args.watch_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
