#!/usr/bin/env python3
"""Offline digest and gate check for an HDFS-19/20 heartbeat bridge release."""

import hashlib
import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def verify_file(record):
    path = Path(record["path"])
    assert path.is_file(), path
    assert digest(path.read_bytes()) == record["sha256"], path


def main(release_dir):
    release_dir = Path(release_dir).resolve()
    receipt = json.loads((release_dir / "release-receipt.json").read_text())
    assert receipt["status"] == "immutable_release_offline_attested_healthy_pending"
    artifacts = receipt["artifacts"]
    for record in artifacts:
        verify_file(record)
    jar = release_dir / "mallory-hdfs-adapter.jar"
    jar_sha = digest(jar.read_bytes())
    assert release_dir.name == jar_sha
    agent_copy = receipt["instrumentation_copy"]
    agent = Path(agent_copy["release_path"])
    assert agent.parent == release_dir
    assert digest(agent.read_bytes()) == agent_copy["sha256"]
    with zipfile.ZipFile(jar) as archive:
        for name, expected in receipt["jar_classes_sha256"].items():
            assert digest(archive.read(name)) == expected, name

    for report in receipt["focused_tests"]:
        name = report["suite"].split(".")[-1]
        xml = ET.parse(release_dir / (name + ".xml")).getroot()
        for field in ("tests", "failures", "errors", "skipped"):
            assert int(xml.attrib[field]) == report[field], (name, field)
        assert report["tests"] > 0
        assert report["failures"] == report["errors"] == report["skipped"] == 0

    for case_id in ("HDFS-19", "HDFS-20"):
        config = json.loads((release_dir / (case_id + "-healthy-only.json")).read_text())
        assert config["case_id"] == case_id
        assert config["calibration_only"] is True
        assert config["auto_promote_if_healthy"] is False
        assert config["agent_properties"]["adapter.jar"] == str(jar)
        assert config["agent_jar"] == str(agent)
        assert config["mapping"]["bridge_adapter_sha256"] == jar_sha
        assert config["mapping"]["agent_sha256"] == agent_copy["sha256"]
        assert config["mapping"]["healthy_seed_verified"] is False
        assert config["mapping"]["verified_healthy_probe"] is None
        for artifact in config["runtime_artifacts"]:
            verify_file(artifact)
        assert any(record["path"] == str(jar) and record["sha256"] == jar_sha
                   for record in config["runtime_artifacts"])

    gate = receipt["healthy_gate"]
    assert gate["live_cluster_runs_completed"] == 0
    assert gate["fault_runs_authorized"] is False
    print("HDFS-19/20 immutable heartbeat bridge offline attestation: PASS", jar_sha)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_immutable_release.py RELEASE_DIRECTORY")
    main(sys.argv[1])
