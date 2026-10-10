#!/usr/bin/env python3
"""Pinned node2 entry points for SOLR-37/38 full and SOLR-39 healthy.

The SOLR-39 full configuration is deliberately withheld until its existing
cluster JUnit passes a fresh exact-target healthy calibration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import sys


BASE = Path("/users/ZhenyuLi/baseline")
RELEASES = BASE / "Mallory/dispatch/releases"
CASES = {
    "SOLR-37": {
        "config": "Mallory/adapters/solr/cases/SOLR-37/config-v48-lane3-full.json",
        "config_sha": "969cdbffe2311b622be2f5ad5a8556d1b67c1d4998c76b2ce7682489d06e4480",
        "core": "2101b380daf3c963b13ad2ffe79ce6f30c9b33c5fedb46e227251f55f6558f5f",
        "manifest_sha": "1fe02b6ae572811c988fa1fa4f569aee18b6907a21e07e1f7b2dbcac587d420d",
        "lock": "/tmp/mallory-lanes/solr-lane3.lock",
        "out": "data/mallory/campaign_v48_lane3/SOLR-37",
        "mode": "full",
    },
    "SOLR-38": {
        "config": "Mallory/adapters/solr/cases/SOLR-38/config-v48-lane1-full.json",
        "config_sha": "7d92b38a1ea56d0d5560d6cb631632da57b2a6583f3a9d4aec39ddc6f4934617",
        "core": "5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf",
        "manifest_sha": "101e132c7513ac37650276d858da4b5cb766903e38be06158db2d4c472c0417f",
        "lock": "/tmp/mallory-lanes/solr-lane1.lock",
        "out": "data/mallory/campaign_v48_lane1/SOLR-38",
        "mode": "full",
    },
    "SOLR-39": {
        "config": "Mallory/adapters/solr/cases/SOLR-39/config-v48-routed-alias-healthy.json",
        "config_sha": "0b9980717f25e858aa33c758e712602868fc9f7257000592638a90e50c6c080e",
        "core": "4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4",
        "manifest_sha": "a679d1d67144e41234b0af1e2cfd399d014dc13d99ba0acfe9ed8116258a6d15",
        "lock": "/tmp/mallory-lanes/solr-routed-alias-v48.lock",
        "out": "data/mallory/calibration_v48_routed_alias/SOLR-39",
        "mode": "healthy_only",
    },
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preflight(case_id: str) -> tuple[dict, Path, Path, Path]:
    row = CASES[case_id]
    config_path = BASE / row["config"]
    release_root = RELEASES / row["core"]
    manifest_path = release_root / "manifest.json"
    output = BASE / row["out"]
    if sha(config_path) != row["config_sha"] or sha(manifest_path) != row["manifest_sha"]:
        raise ValueError("immutable Solr config or core manifest SHA changed")
    if output.exists():
        raise ValueError(f"output is not fresh: {output}")
    sys.path.insert(0, str(release_root))
    sys.path.insert(1, str(BASE))
    from Mallory.core.campaign import validate_config
    from Mallory.dispatch.core_release import verify
    from Mallory.dispatch.scheduler import verify_runtime_artifacts
    from Mallory.dispatch.verify_sources import (case_expected_files,
                                                  verify_from_reference)

    verify(manifest_path)
    config = json.loads(config_path.read_text())
    validate_config(config)
    verify_runtime_artifacts(config)
    if config["case_id"] != case_id or config["system"] != "solr":
        raise ValueError("case identity differs")
    if row["mode"] == "full":
        if (config["calibration_only"] or config["mapping"]["status"] != "runtime_attested"
                or config["budget"]["trials"] != 80
                or config["budget"]["seconds"] != 3600
                or config["budget"]["max_faults_per_trial"] != 3):
            raise ValueError("full campaign or healthy attestation differs")
    elif not config["calibration_only"]:
        raise ValueError("SOLR-39 is authorized for healthy calibration only")
    inventory = json.loads((BASE / "Mallory/adapters/solr/releases/v20/inventory.json").read_text())
    case_row, = (r for r in inventory["cases"] if r["case_id"] == case_id)
    reference = json.loads((BASE / "Mallory/adapters/solr/releases/v20/source_reference.json").read_text())
    source_root = Path(config["source_equivalent_root"])
    provenance = case_row["provenance"]
    verdict = verify_from_reference({"name": "local", "kind": "local"}, Path(),
                                    Path(provenance["source_root"]),
                                    provenance["source_commit"], reference, source_root)
    if not verdict["content_match"]:
        raise ValueError("source checkout differs from pinned Solr commit")
    for path, expected in case_expected_files(case_row, config):
        if sha(path) != expected:
            raise ValueError(f"target/test source SHA differs: {path}")
    return row, config_path, release_root, output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_id", choices=sorted(CASES))
    parser.add_argument("--launch", action="store_true", help="requires dispatch host admission")
    args = parser.parse_args()
    row, config_path, release_root, output = preflight(args.case_id)
    receipt = {"case_id": args.case_id, "mode": row["mode"],
               "config_sha256": row["config_sha"], "core_release": row["core"],
               "core_manifest_sha256": row["manifest_sha"],
               "lock": row["lock"], "output": str(output), "preflight": "passed"}
    if not args.launch:
        print(json.dumps(receipt, sort_keys=True), flush=True)
        return
    if "node2" not in socket.gethostname():
        raise ValueError("these isolated source lanes are staged on node2 only")
    stat = os.statvfs(BASE)
    disk_free = stat.f_bavail * stat.f_frsize
    meminfo = Path("/proc/meminfo").read_text()
    mem_available = next(int(line.split()[1]) * 1024 for line in meminfo.splitlines()
                         if line.startswith("MemAvailable:"))
    load = os.getloadavg()[0]
    if disk_free < 5 * 1024**3 or mem_available < 16 * 1024**3 or load >= 12:
        raise ValueError("node2 capacity gate failed")
    Path(row["lock"]).parent.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    print(json.dumps({**receipt, "disk_free": disk_free,
                      "mem_available": mem_available, "load1": load,
                      "launch": True}, sort_keys=True), flush=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{release_root}:{BASE}"
    os.execvpe("flock", ["flock", "-n", row["lock"], sys.executable,
                         "-m", "Mallory.core.campaign", "--config", str(config_path),
                         "--out", str(output)], env)


if __name__ == "__main__":
    main()
