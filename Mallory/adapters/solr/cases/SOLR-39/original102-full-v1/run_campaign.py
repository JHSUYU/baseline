#!/usr/bin/env python3
"""Offline preflight and GO-gated original-102 Solr cluster JUnit campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
CASE = HERE.parent.name
RELEASE = ROOT / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
OUT_ROOT = ROOT / "data/mallory/original102_full_v1_node2" / CASE
sys.path.insert(0, str(RELEASE))
from Mallory.core import campaign  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def preflight(mode: str) -> dict:
    manifest = read(HERE / "sha-manifest.json")
    if manifest["case_id"] != CASE:
        raise ValueError("wrong package manifest")
    for name, record in manifest["files"].items():
        path = HERE / name
        if (not path.is_file() or path.stat().st_size != record["bytes"]
                or sha(path) != record["sha256"]):
            raise ValueError(f"case-local file changed: {name}")
    config_path = HERE / f"config-{mode}-node2.json"
    config = read(config_path)
    if config["case_id"] != CASE or config["site_file"] != str(HERE / "sites.json"):
        raise ValueError("wrong case or site file")
    if config["budget"] != {"trials": 80, "seconds": 3600,
                            "max_faults_per_trial": 3, "trial_timeout_seconds": 480}:
        raise ValueError("full budget changed")
    if (bool(config["calibration_only"]) != (mode == "healthy") or
            bool(config["auto_promote_if_healthy"]) != (mode == "full") or
            config.get("fault_types") != ["EXCEPTION"] or
            config.get("require_event_time_paths") is not False):
        raise ValueError("mode or fault admission changed")
    if config["core_release"] != str(RELEASE) or not Path(campaign.__file__).resolve().is_relative_to(RELEASE):
        raise ValueError("graph-order core is not pinned")
    sites = read(HERE / "sites.json")
    target_lines = {(row["clazz"], row["line"]) for row in sites["targets"]}
    for check in config["target"]["check_sites"]:
        clazz, line = check.split("#", 1)[0], int(check.rsplit("@", 1)[1].split(":", 1)[0])
        if (clazz, line) not in target_lines:
            raise ValueError("selected target absent from site catalog")
    if not sites["doors"] or not sites["regions"]:
        raise ValueError("injectable I/O or target region missing")
    for row in config["runtime_artifacts"]:
        path = Path(row["path"])
        if not path.is_file() or sha(path) != row["sha256"]:
            raise ValueError(f"runtime artifact changed: {path}")
    source = Path(config["cwd"])
    if not source.is_dir() or config["source_equivalent_root"] != str(source):
        raise ValueError("source checkout missing")
    inventory = read(ROOT / "Mallory/adapters/solr/releases/v20/inventory.json")
    row = next(item for item in inventory["cases"] if item["case_id"] == CASE)
    test_rel = row["workload"]["test_source_path"]
    if sha(source / test_rel) != config["mapping"]["test_source_sha256"]:
        raise ValueError("selected JUnit source changed")
    if sha(source / config["target"]["source_path"]) != config["mapping"]["target_source_sha256"]:
        raise ValueError("target source changed")
    compiled = Path(config["mapping"]["compiled_jar"])
    if sha(compiled) != config["mapping"]["compiled_jar_sha256"]:
        raise ValueError("compiled JAR changed")
    member = config["target"]["check_sites"][0].split("#", 1)[0].replace(".", "/") + ".class"
    with zipfile.ZipFile(compiled) as archive:
        class_hash = hashlib.sha256(archive.read(member)).hexdigest()
    if class_hash != config["mapping"]["compiled_class_sha256"]:
        raise ValueError("compiled target class changed")
    campaign.validate_config(config)
    return {"config_sha256": sha(config_path), "site_sha256": sha(HERE / "sites.json"),
            "agent_sha256": sha(Path(config["agent_jar"])),
            "adapter_sha256": sha(Path(config["agent_properties"]["adapter.jar"])),
            "core_manifest_sha256": sha(RELEASE / "manifest.json")}


def admit_prior_healthy() -> dict:
    if CASE != "SOLR-39":
        return {}
    root = OUT_ROOT / "healthy"
    result_path, trial_path = root / "result.json", root / "trials/r0000/result.json"
    if not result_path.is_file() or not trial_path.is_file() or not (root / "config.json").is_file():
        raise ValueError("fresh SOLR-39 healthy result missing")
    if sha(root / "config.json") != sha(HERE / "config-healthy-node2.json"):
        raise ValueError("healthy config differs")
    result, trial = read(result_path), read(trial_path)
    if (result.get("status") != "calibration_complete" or not result.get("healthy_seed_valid")
            or result.get("healthy_junit_validation", {}).get("status") != "passed"
            or result.get("healthy_junit_validation", {}).get("tests") != 1
            or not result.get("runtime_attestation", {}).get("valid")
            or not result.get("target_binding", {}).get("nodes")
            or trial.get("plan") != []):
        raise ValueError("SOLR-39 healthy JUnit, target identity or I/O admission failed")
    feedback = trial.get("feedback", {})
    if feedback.get("target_threw") or not feedback.get("target_instances"):
        raise ValueError("SOLR-39 healthy target absent or threw")
    named = set(result["target_binding"]["nodes"])
    doors = [row for row in feedback.get("doors", [])
             if row.get("point", {}).get("node") in named and row.get("fault_type") == "EXCEPTION"]
    if not doors or result.get("healthy_eligible_doors", 0) <= 0:
        raise ValueError("SOLR-39 healthy lacks named pretarget injectable I/O")
    return {"healthy_result_sha256": sha(result_path), "healthy_trial_sha256": sha(trial_path),
            "named_pretarget_io_doors": len(doors)}


def check_go(mode: str, path: Path, config_sha: str, out: Path) -> str:
    receipt = read(path)
    if (receipt.get("go") is not True or receipt.get("host") != "node2"
            or receipt.get("case_id") != CASE or receipt.get("mode") != mode
            or receipt.get("config_sha256") != config_sha
            or receipt.get("runner_sha256") != sha(Path(__file__))
            or receipt.get("intended_output") != str(out)):
        raise ValueError("dispatch GO receipt absent or mismatched")
    return sha(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = ("healthy", "full") if CASE == "SOLR-39" else ("full",)
    parser.add_argument("--mode", choices=modes, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    metadata = preflight(args.mode)
    out = OUT_ROOT / args.mode
    if args.preflight_only:
        print(json.dumps({"preflight": "passed", "case_id": CASE,
                          "mode": args.mode, **metadata}, sort_keys=True))
        return 0
    if args.admission_receipt is None:
        parser.error("dispatch GO receipt required before starting a JVM")
    if args.mode == "full":
        metadata.update(admit_prior_healthy())
    metadata["admission_sha256"] = check_go(args.mode, args.admission_receipt,
                                            metadata["config_sha256"], out)
    print(json.dumps({"preflight": "passed", "case_id": CASE,
                      "mode": args.mode, **metadata}, sort_keys=True), flush=True)
    state = campaign.run(HERE / f"config-{args.mode}-node2.json", out)
    print(json.dumps({"status": state["status"],
                      "completed_trials": state["completed_trials"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
