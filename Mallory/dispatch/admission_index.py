"""Build a resumable, conservative admission ledger for all 102 original checks.

This read-only discovery step never starts a JVM or silently promotes a seed.
Each system queue names either a formally pinned campaign candidate or the
exact reason that case cannot enter a fault campaign yet.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time

from .archive import TERMINAL
from .collect import sha256
from .core_release import verify as verify_core_release
from .worker import atomic_json


CORE_AUDIT_FILES = ("audit.py", "events.py", "graph.py", "feedback.py", "campaign.py")


def _read(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def _healthy_proof(path: Path, case_id: str, expected_core: dict[str, str]) -> dict | None:
    result_path = path / "result.json"
    audit_path = path / "offline-causal-audit.json"
    result = _read(result_path)
    audit = _read(audit_path)
    if not result or not audit:
        return None
    if (result.get("case_id") != case_id
            or result.get("status") != "calibration_complete"
            or result.get("healthy_seed_valid") is not True
            or result.get("fault_trials_completed") != 0
            or audit.get("campaign_result_sha256") != sha256(result_path)
            or audit.get("core_source_sha256") != expected_core
            or audit.get("report_gate_passed") is not True
            or audit.get("healthy_closure_proven") is not True
            or not isinstance(audit.get("healthy_observed_path_doors"), int)
            or isinstance(audit.get("healthy_observed_path_doors"), bool)
            or audit["healthy_observed_path_doors"] < 1):
        return None
    return {"path": str(path), "result_sha256": sha256(result_path),
            "audit_path": str(audit_path), "audit_sha256": sha256(audit_path),
            "observed_path_doors": audit["healthy_observed_path_doors"],
            "duration_seconds": result.get("duration_seconds")}


def _external_receipt_valid(path: Path, published: dict, result_sha: str,
                            trial_count: int) -> bool:
    if (published.get("result_sha256") or
            published.get("campaign_result_sha256")) != result_sha:
        return False
    validated = published.get("validated_trials")
    if validated is not None:
        if not isinstance(validated, list) or len(validated) != trial_count:
            return False
        ids = set()
        for trial in validated:
            trial_id = trial.get("trial_id") if isinstance(trial, dict) else None
            if not isinstance(trial_id, int) or trial_id in ids:
                return False
            ids.add(trial_id)
            trial_dir = path / "trials" / f"r{trial_id:04d}"
            if (not (trial_dir / "result.json").is_file()
                    or sha256(trial_dir / "result.json") != trial.get("result_sha256")
                    or not (trial_dir / "events.jsonl.gz").is_file()
                    or _sha256_gunzip(trial_dir / "events.jsonl.gz")
                    != trial.get("events_sha256")):
                return False
    elif published.get("trials_audited") is not None:
        if (published.get("attestation") != "passed"
                or published.get("trials_audited") != trial_count):
            return False
        for relative, digest in (
            ("config.json", published.get("campaign_config_sha256")),
            (published.get("source_snapshot_path"), published.get("source_snapshot_sha256")),
            (published.get("archived_compiled_target_path"),
             published.get("archived_compiled_target_sha256")),
            (published.get("agent_jar_path"), published.get("agent_jar_sha256")),
        ):
            if not isinstance(relative, str) or not isinstance(digest, str):
                return False
            artifact = path / relative
            if not artifact.is_file() or sha256(artifact) != digest:
                return False
    else:
        return False
    return True


def _sha256_gunzip(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with gzip.open(path, "rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except (OSError, EOFError):
        return "invalid_gzip"
    return digest.hexdigest()


def _source_gap(repo: Path, data_root: Path, case_id: str) -> dict | None:
    receipt = _read(data_root / "source_gaps" / case_id / "receipt.json")
    if (not receipt or receipt.get("schema_version") != 1
            or receipt.get("case_id") != case_id
            or receipt.get("status") != "no_suitable_cluster_test"):
        return None
    review_relative = receipt.get("review_path")
    if not isinstance(review_relative, str):
        return None
    review_path = (repo / review_relative).resolve()
    if (not review_path.is_relative_to(repo / "Mallory/cases/revisions")
            or not review_path.is_file()
            or sha256(review_path) != receipt.get("review_sha256")):
        return None
    review = _read(review_path)
    if (not review or review.get("status") != "no_suitable_existing_cluster_test_identified"
            or not isinstance(review.get("cases"), list)):
        return None
    candidate = next((item for item in review["cases"]
                      if item.get("case_id") == case_id), None)
    if not candidate:
        return None
    if (receipt.get("healthy_result_sha256") != candidate.get("current_healthy_result_sha256")
            or receipt.get("audit_sha256") != candidate.get("current_offline_audit_sha256")):
        return None
    for key, digest_key in (("current_healthy_result", "current_healthy_result_sha256"),
                            ("current_offline_audit", "current_offline_audit_sha256")):
        relative = candidate.get(key)
        if not isinstance(relative, str):
            return None
        artifact = (repo / relative).resolve()
        if (not artifact.is_relative_to(data_root)
                or not artifact.is_file()
                or sha256(artifact) != candidate.get(digest_key)):
            return None
    audit = _read(repo / candidate["current_offline_audit"])
    if not audit or audit.get("healthy_observed_path_doors") != 0:
        return None
    return {"review_path": str(review_path), "review_sha256": sha256(review_path),
            "healthy_result_sha256": candidate["current_healthy_result_sha256"],
            "audit_sha256": candidate["current_offline_audit_sha256"]}


def _complete_case(path: Path, case_id: str, expected_core: dict[str, str],
                   data_root: Path) -> dict | None:
    result_path = path / "result.json"
    result = _read(result_path)
    audit = _read(path / "offline-causal-audit.json")
    if (not result or not audit or result.get("case_id") != case_id
            or result.get("status") not in TERMINAL["campaign"]
            or audit.get("campaign_result_sha256") != sha256(result_path)
            or audit.get("core_source_sha256") != expected_core
            or audit.get("report_gate_passed") is not True
            or audit.get("healthy_observed_path_doors", 0) < 1):
        return None
    archive = result.get("evidence_archive") or {}
    mode = "bound_campaign_archive"
    if archive:
        packed = data_root / archive.get("path", "")
        manifest = data_root / archive.get("manifest_path", "")
        if (not packed.is_file() or not manifest.is_file()
                or sha256(packed) != archive.get("sha256")
                or sha256(manifest) != archive.get("manifest_sha256")):
            return None
        archive_sha = archive["sha256"]
    else:
        # Historical externally launched full campaigns retain their immutable
        # raw result and independent SHA receipts.  They should never be
        # rescheduled merely because their controller predates evidence_archive.
        compact = _read(path / "evidence-compaction.json")
        published = (_read(path / "publish-receipt.json")
                     or _read(path / "sync-receipt.json")
                     or _read(path / "posthoc-attestation.json"))
        if compact:
            packed = data_root / compact.get("archive_relative", "")
            manifest = packed.with_name(packed.name.removesuffix(".tar.gz")
                                        + ".manifest.json")
            if (compact.get("result_sha256") != sha256(result_path)
                    or compact.get("audit_sha256") != sha256(path / "offline-causal-audit.json")
                    or not packed.is_file() or not manifest.is_file()
                    or sha256(packed) != compact.get("archive_sha256")
                    or sha256(manifest) != compact.get("manifest_sha256")):
                return None
            archive_sha = compact["archive_sha256"]
            mode = "bound_external_replay_archive"
        elif published:
            trial_count = len(list(path.glob("trials/r*/result.json")))
            if (trial_count < 1 or trial_count != audit.get("trial_count")
                    or not _external_receipt_valid(path, published,
                                                   sha256(result_path), trial_count)):
                return None
            archive_sha = None
            mode = "sha_receipted_external_raw"
        else:
            return None
    return {"result_sha256": sha256(result_path),
            "audit_sha256": sha256(path / "offline-causal-audit.json"),
            "archive_sha256": archive_sha, "evidence_mode": mode,
            "status": result["status"],
            "duration_seconds": result.get("duration_seconds")}


def _configs(repo: Path, data_root: Path) -> dict[str, list[tuple[Path, dict]]]:
    roots = [repo / "Mallory/adapters", data_root / "promoted_configs"]
    configs: dict[str, list[tuple[Path, dict]]] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.json"):
            value = _read(path)
            if (not value or not isinstance(value.get("case_id"), str)
                    or value.get("mapping", {}).get("status") != "runtime_attested"
                    or value.get("calibration_only") is not False
                    or value.get("auto_promote_if_healthy") is not True):
                continue
            configs.setdefault(value["case_id"], []).append((path, value))
    return configs


def build(*, repo: Path, data_root: Path, inventory_path: Path,
          source_reference: Path, release_manifest: Path, output_root: Path,
          active_cases: set[str] | None = None) -> dict:
    repo = repo.resolve()
    data_root = data_root.resolve()
    inventory = _read(inventory_path)
    reference = _read(source_reference)
    if (not inventory or not reference
            or reference.get("inventory_sha256") != sha256(inventory_path)):
        raise ValueError("inventory and source reference are not a pinned pair")
    release = verify_core_release(release_manifest.resolve())
    expected_core = {name: release["files"][f"Mallory/core/{name}"]
                     for name in CORE_AUDIT_FILES}
    available_configs = _configs(repo, data_root)
    by_system: dict[str, list[dict]] = {}
    seen = set()
    for row in inventory["cases"]:
        case_id = row["case_id"]
        if case_id in seen:
            raise ValueError(f"duplicate original check: {case_id}")
        seen.add(case_id)
        system = row["system"]
        entry: dict = {"case_id": case_id, "system": system}
        completed = _complete_case(data_root / "cases" / case_id, case_id,
                                   expected_core, data_root)
        if completed:
            entry.update({"state": "completed_high_quality", "terminal": completed})
        elif case_id in (active_cases or set()):
            entry.update({"state": "active_held", "reason": "live pinned campaign"})
        elif row.get("eligibility", {}).get("may_dispatch_healthy_seed") is False:
            eligibility = row["eligibility"]
            entry.update({"state": "source_or_workload_ineligible",
                          "reason": eligibility.get("state"),
                          "mapping_gaps": eligibility.get("mapping_gaps", [])})
        else:
            attempts = [p.parent for p in data_root.glob(f"calibration*/{case_id}*/result.json")]
            proofs = [proof for path in attempts
                      if (proof := _healthy_proof(path, case_id, expected_core))]
            proofs.sort(key=lambda proof: (-proof["observed_path_doors"], proof["path"]))
            if not proofs:
                latest = max(attempts, key=lambda path: (path / "result.json").stat().st_mtime,
                             default=None)
                gap = _source_gap(repo, data_root, case_id)
                if gap:
                    entry.update({"state": "no_suitable_cluster_test",
                                  "reason": "no observed causal door in available cluster workload",
                                  "source_gap": gap})
                else:
                    entry.update({"state": "healthy_repair_needed" if latest else "healthy_unrun",
                                  "latest_attempt": str(latest) if latest else None,
                                  "latest_status": (_read(latest / "result.json") or {}).get("status")
                                  if latest else None})
            else:
                matching = []
                needs_revision = []
                for proof in proofs:
                    for path, config in available_configs.get(case_id, []):
                        attestation = (config.get("calibration_attestation") or {})
                        pinned_audit = attestation.get("healthy_causal_audit") or {}
                        if (pinned_audit.get("sha256") != proof["audit_sha256"]
                                or config.get("system") != system
                                or config.get("budget", {}).get("trials", 0) > 80
                                or config.get("budget", {}).get("seconds", 0) > 3600):
                            continue
                        candidate = {"path": str(path), "sha256": sha256(path),
                                     "source_root": config.get("source_equivalent_root")
                                     or config.get("cwd"),
                                     "healthy_proof": proof}
                        if config.get("cluster_test") == row.get("workload", {}).get("selected_selector"):
                            matching.append(candidate)
                        else:
                            needs_revision.append(candidate)
                if matching:
                    entry["healthy_proof"] = matching[0]["healthy_proof"]
                    entry.update({"state": "promoted_candidate_preflight_required",
                                  "promoted_configs": matching})
                elif needs_revision:
                    entry["healthy_proof"] = needs_revision[0]["healthy_proof"]
                    entry.update({"state": "versioned_selector_admission_required",
                                  "promoted_configs": needs_revision})
                else:
                    entry["healthy_proof"] = proofs[0]
                    entry.update({"state": "healthy_proven_promotion_pending",
                                  "reason": "no exact SHA-bound runtime_attested config"})
        by_system.setdefault(system, []).append(entry)
    if len(seen) != 102:
        raise ValueError(f"original checklist has {len(seen)} cases, expected 102")
    output_root.mkdir(parents=True, exist_ok=True)
    summary = {"schema_version": 1, "inventory_sha256": sha256(inventory_path),
               "source_reference_sha256": sha256(source_reference),
               "core_release_id": release["release_id"], "generated_at": time.time(),
               "systems": {system: {"cases": len(entries),
                                    "states": {state: sum(x["state"] == state for x in entries)
                                               for state in sorted({x["state"] for x in entries})}}
                           for system, entries in sorted(by_system.items())}}
    for system, entries in by_system.items():
        atomic_json(output_root / f"{system}.json", {
            "schema_version": 1, "system": system,
            "inventory_sha256": summary["inventory_sha256"],
            "source_reference_sha256": summary["source_reference_sha256"],
            "core_release_id": release["release_id"],
            "cases": entries})
    atomic_json(output_root / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--data-root", type=Path, default=Path("data/mallory"))
    parser.add_argument("--inventory", type=Path, default=Path("Mallory/cases/inventory.json"))
    parser.add_argument("--source-reference", type=Path,
                        default=Path("Mallory/dispatch/source_reference.json"))
    parser.add_argument("--core-release-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path,
                        default=Path("data/mallory/dispatch/admission_index"))
    parser.add_argument("--active-case", action="append", default=[])
    args = parser.parse_args()
    print(json.dumps(build(repo=args.repo, data_root=args.data_root,
                           inventory_path=args.inventory,
                           source_reference=args.source_reference,
                           release_manifest=args.core_release_manifest,
                           output_root=args.output_root,
                           active_cases=set(args.active_case)), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
