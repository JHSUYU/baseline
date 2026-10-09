"""Read-only HDFS-31/32 original-JUnit healthy admission gate.

Run only after dispatch has produced a fresh campaign and frozen-core
``offline-causal-audit.json``. This script does not launch a JVM or edit data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
RELEASE = REPO / "Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf/manifest.json"
AUDIT_FILES = ("audit.py", "events.py", "graph.py", "feedback.py", "campaign.py")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check(case_id: str, campaign: Path) -> list[str]:
    errors: list[str] = []
    config_path = HERE / f"{case_id}-original-junit-healthy-v1.json"
    config = read_json(config_path)
    mapping = config["mapping"]
    release = read_json(RELEASE)
    requirement = config["healthy_gate"]
    preflight = Path(mapping["preflight_receipt"])
    invalid = Path(mapping["invalid_healthy_result"])

    if config["case_id"] != case_id or not config["calibration_only"]:
        errors.append("wrong case or not healthy-only")
    if config["budget"]["trials"] != 1:
        errors.append("healthy-only config does not request exactly one trial")
    if sha256(RELEASE) != mapping["core_release_manifest_sha256"]:
        errors.append("frozen core manifest hash changed")
    if release.get("release_id") != mapping["core_release_id"]:
        errors.append("wrong frozen core release")
    if not preflight.is_file() or sha256(preflight) != mapping["preflight_receipt_sha256"]:
        errors.append("linkage preflight receipt missing or changed")
    if not invalid.is_file() or sha256(invalid) != mapping["invalid_healthy_result_sha256"]:
        errors.append("archived invalid startup evidence missing or changed")
    for artifact in config["runtime_artifacts"]:
        path = Path(artifact["path"])
        if not path.is_file() or sha256(path) != artifact["sha256"]:
            errors.append("pinned runtime artifact changed: " + str(path))
    if not (campaign / "config.json").is_file() or sha256(campaign / "config.json") != sha256(config_path):
        errors.append("campaign config differs from this immutable original-JUnit revision")

    required = ("result.json", "trials/r0000/result.json", "offline-causal-audit.json")
    missing = [name for name in required if not (campaign / name).is_file()]
    if missing:
        return errors + ["missing " + name for name in missing]

    summary = read_json(campaign / "result.json")
    trial = read_json(campaign / "trials/r0000/result.json")
    audit = read_json(campaign / "offline-causal-audit.json")
    feedback = trial.get("feedback") or {}
    junit = summary.get("healthy_junit_validation") or {}

    if summary.get("case_id") != case_id or trial.get("case_id") != case_id:
        errors.append("wrong result case ID")
    if summary.get("cluster_test") != config["cluster_test"]:
        errors.append("wrong JUnit selector")
    if summary.get("target") != config["target"]:
        errors.append("result does not bind exact selected check")
    if summary.get("healthy_seed_valid") is not True:
        errors.append("runner did not validate healthy seed")
    if summary.get("status") not in ("calibration_complete", "healthy_seed_valid"):
        errors.append("healthy calibration not complete")
    if junit.get("status") != "passed" or junit.get("runner") != "surefire_xml":
        errors.append("fresh Surefire JUnit receipt did not pass")
    if junit.get("tests") != requirement["required_junit_tests"]:
        errors.append("JUnit test count differs from selected method")
    for key in ("errors", "failures", "skipped"):
        if junit.get(key) != 0:
            errors.append("JUnit " + key + " nonzero or unavailable")
    if trial.get("return_code") != 0 or trial.get("timed_out") is not False:
        errors.append("runner failed or timed out")
    if feedback.get("target_reached") is not True or feedback.get("target_threw") is not False:
        errors.append("exact selected target absent or threw in healthy run")
    if feedback.get("target_identity_complete") is not True or feedback.get("target_identity_gaps"):
        errors.append("target runtime identity incomplete")
    instances = feedback.get("target_instances") or []
    if not instances or any(
        not str(item.get("node", "")).startswith("hdfs-cluster-")
        or "/dn" not in str(item.get("node", ""))
        for item in instances
    ):
        errors.append("target occurrence outside named DataNode actor")
    catalog = trial.get("site_catalog_validation") or {}
    if (catalog.get("valid") is not True or catalog.get("class_hash_match") is not True
            or catalog.get("missing_check_sites") or catalog.get("duplicate_target_sites")):
        errors.append("compiled selected check site not attested")
    attestation = summary.get("runtime_attestation") or {}
    if (attestation.get("valid") is not True
            or attestation.get("expected_target_class_sha256") != config["expected_target_class_sha256"]
            or attestation.get("observed_target_class_sha256") != config["expected_target_class_sha256"]):
        errors.append("runtime target class attestation missing or mismatched")

    if audit.get("campaign_result_sha256") != sha256(campaign / "result.json"):
        errors.append("offline audit does not bind this campaign result")
    expected_core = {name: release["files"]["Mallory/core/" + name] for name in AUDIT_FILES}
    if audit.get("core_source_sha256") != expected_core:
        errors.append("offline audit did not use pinned frozen core")
    if audit.get("allow_local_timeline_doors", False) is not False:
        errors.append("local timeline fallback enabled")
    if audit.get("report_gate_passed") is not True or audit.get("healthy_closure_proven") is not True:
        errors.append("offline causal audit gate failed")
    if audit.get("healthy_observed_path_doors", 0) < requirement["minimum_healthy_observed_path_doors"]:
        errors.append("no observed graph-path door into named target closure")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, choices=("HDFS-31", "HDFS-32"))
    parser.add_argument("--campaign", required=True, type=Path)
    args = parser.parse_args()
    errors = check(args.case, args.campaign)
    print(json.dumps({"case_id": args.case, "campaign": str(args.campaign),
                      "admitted": not errors, "errors": errors}, indent=2))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
