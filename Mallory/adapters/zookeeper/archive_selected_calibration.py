#!/usr/bin/env python3
"""Make a self-contained ZooKeeper healthy-calibration evidence bundle."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from Mallory.adapters.zookeeper.attest_selected_calibration import CASES


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive(evidence: Path) -> None:
    command = json.loads((evidence / "command.json").read_text(encoding="utf-8"))
    pins = json.loads((evidence / "pins.json").read_text(encoding="utf-8"))
    attestation = json.loads((evidence / "attestation.json").read_text(encoding="utf-8"))
    assert attestation["case_id"] == command["case_id"]
    spec = CASES[command["case_id"]]
    source = Path(command["cwd"])
    root = Path("/users/ZhenyuLi/baseline")
    receipt = Path(pins["source_overlay_receipt"])
    agent = root / "data/mallory/calibration/agent-builds/mallory-agent-causal-context-bf8e6dba.jar"
    report_dir = source / "zookeeper-server/target/surefire-reports"
    report_name = spec["test_class"] + "-" + command["report_suffix"]
    copies = {
        "junit/TEST-" + report_name + ".xml": report_dir / ("TEST-" + report_name + ".xml"),
        "junit/" + report_name + "-output.txt": report_dir / (report_name + "-output.txt"),
        "inputs/target.java": source / spec["target_source"],
        "inputs/test.java": source / spec["test_source"],
        "inputs/target.class": source / spec["compiled_class"],
        "inputs/mallory-agent.jar": agent,
        "inputs/source-overlay-receipt.json": receipt,
        "inputs/source-overlay.patch": Path(json.loads(receipt.read_text(encoding="utf-8"))["patch_file"]),
    }
    for relative, original in copies.items():
        target = evidence / relative
        assert not target.exists(), f"refusing to overwrite {target}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        assert sha(target) == sha(original)
    all_names = ["command.json", "pins.json", "agent.properties", "sites.json", "exit.json",
                 "events.jsonl", "catalog.jsonl", "maven.log", "attestation.json"] + sorted(copies)
    manifest = {
        "schema_version": 1, "case_id": command["case_id"],
        "scope": "Healthy calibration only; test-data is ephemeral and excluded",
        "files": {name: sha(evidence / name) for name in all_names},
        "source_path": str(source), "agent_path": str(agent),
    }
    (evidence / "archive-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    archive(args.evidence)
