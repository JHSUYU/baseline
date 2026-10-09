"""Read-only admission gate for the HDFS-29 lease-recovery healthy seed.

Run after the frozen-core offline causal audit has produced
``offline-causal-audit.json`` in a new calibration_v16/HDFS-29 directory.
This gate neither starts a JVM nor changes the campaign.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


CONFIG = Path(__file__).with_name("HDFS-29-lease-recovery-healthy-v16.json")
REPO = Path(__file__).resolve().parents[5]
RELEASE = REPO / "Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf/manifest.json"
AUDIT_FILES = ("audit.py", "events.py", "graph.py", "feedback.py", "campaign.py")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check(campaign: Path) -> list[str]:
    errors: list[str] = []
    config = read_json(CONFIG)
    release = read_json(RELEASE)
    mapping = config["mapping"]

    if sha256(RELEASE) != mapping["core_release_manifest_sha256"]:
        errors.append("frozen core manifest hash changed")
    if release.get("release_id") != mapping["core_release_id"]:
        errors.append("wrong frozen core release")
    if not (campaign / "config.json").is_file() or sha256(campaign / "config.json") != sha256(CONFIG):
        errors.append("campaign config is not the pinned v16 alternate")

    required = ("result.json", "trials/r0000/result.json", "offline-causal-audit.json")
    missing = [name for name in required if not (campaign / name).is_file()]
    if missing:
        return errors + ["missing " + name for name in missing]

    summary = read_json(campaign / "result.json")
    trial = read_json(campaign / "trials/r0000/result.json")
    audit = read_json(campaign / "offline-causal-audit.json")
    feedback = trial.get("feedback") or {}
    junit = summary.get("healthy_junit_validation") or {}
    requirement = config["healthy_gate"]

    if summary.get("case_id") != "HDFS-29" or trial.get("case_id") != "HDFS-29":
        errors.append("wrong case ID")
    if summary.get("healthy_seed_valid") is not True:
        errors.append("runner did not validate healthy seed")
    if summary.get("status") not in ("calibration_complete", "healthy_seed_valid"):
        errors.append("healthy calibration is not complete")
    if junit.get("status") != "passed":
        errors.append("JUnit status is not passed")
    if junit.get("tests") != requirement["required_junit_tests"]:
        errors.append("JUnit test count differs from the one selected method")
    for key in ("errors", "failures", "skipped"):
        if junit.get(key) != 0:
            errors.append("JUnit " + key + " is nonzero or unavailable")
    if trial.get("return_code") != 0 or trial.get("timed_out") is not False:
        errors.append("runner failed or timed out")
    if feedback.get("target_reached") is not True or feedback.get("target_threw") is not False:
        errors.append("selected target was absent or threw in healthy run")
    if feedback.get("target_identity_complete") is not True or feedback.get("target_identity_gaps"):
        errors.append("target runtime identity is incomplete")
    target_instances = feedback.get("target_instances") or []
    if not target_instances or any(
        not str(item.get("node", "")).startswith("hdfs-cluster-")
        or "/dn" not in str(item.get("node", ""))
        for item in target_instances
    ):
        errors.append("selected target is not on named DataNode actor(s)")
    catalog = trial.get("site_catalog_validation") or {}
    if catalog.get("class_hash_match") is not True or catalog.get("missing_check_sites"):
        errors.append("exact compiled target site was not attested")

    if audit.get("campaign_result_sha256") != sha256(campaign / "result.json"):
        errors.append("offline audit does not bind this result")
    expected_core = {name: release["files"]["Mallory/core/" + name] for name in AUDIT_FILES}
    if audit.get("core_source_sha256") != expected_core:
        errors.append("offline audit did not use frozen 5820 core")
    if audit.get("allow_local_timeline_doors", False) is not False:
        errors.append("local timeline fallback was enabled")
    if audit.get("report_gate_passed") is not True or audit.get("healthy_closure_proven") is not True:
        errors.append("offline causal audit gate failed")
    if audit.get("healthy_observed_path_doors", 0) < requirement["minimum_healthy_observed_path_doors"]:
        errors.append("no named pre-target I/O door has an observed graph path")
    # The frozen 5820 audit predates the evidence-types annotation. Its
    # positive observed-path count is the independent graph-path proof.
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path,
                        default=REPO / "data/mallory/calibration_v16/HDFS-29")
    args = parser.parse_args()
    errors = check(args.campaign)
    print(json.dumps({"case_id": "HDFS-29", "campaign": str(args.campaign),
                      "admitted": not errors, "errors": errors}, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
