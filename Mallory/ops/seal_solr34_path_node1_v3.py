#!/usr/bin/env python3
"""Seal the SOLR-34 v3 target-absent, wrong-agent healthy observation."""

import hashlib
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path


BASE = Path(__file__).resolve().parents[2]
RAW = BASE / "data/mallory/healthy_observations/SOLR-34-path-node1-v3"
REMOTE = RAW.with_suffix(".remote-sha-index.json")
ARCHIVES = BASE / "data/mallory/evidence_archives"
NAME = "SOLR-34-path-healthy-node1-v3"
EXPECTED_AGENT = "b4bb6493699d87dceb966ff63b6f727455e5afdbbe1ddce4cd2247faab17eae4"
ACTUAL_AGENT = "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9"


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    remote = json.loads(REMOTE.read_text())
    for name, digest in remote["files"].items():
        p = RAW / name
        if not p.is_file() or sha(p) != digest:
            raise RuntimeError(f"node1 raw changed: {name}")
    result = json.loads((RAW / "result.json").read_text())
    pilot = json.loads((RAW / "trials/r0000/pilot-result.json").read_text())
    config = json.loads((RAW / "config.json").read_text())
    junit = json.loads((RAW / "trials/r0000/junit-receipt.json").read_text())
    if not (result.get("status") == "calibration_complete"
            and result.get("duration_seconds") == 17.48
            and result.get("healthy_seed_valid") is False
            and result.get("fault_trials_completed") == 0
            and pilot.get("agent_sha256") == ACTUAL_AGENT
            and config["mapping"]["agent_sha256"] == EXPECTED_AGENT
            and (junit.get("status"), junit.get("tests"), junit.get("failures"),
                 junit.get("errors")) == ("passed", 1, 0, 0)):
        raise RuntimeError("SOLR-34 diagnostic outcome changed")
    quality = {
        "schema_version": 1, "case_id": "SOLR-34",
        "status": "healthy_target_absent_wrong_agent",
        "junit_1_0_0": True, "fault_trials": 0,
        "expected_agent_sha256": EXPECTED_AGENT,
        "observed_pilot_agent_sha256": ACTUAL_AGENT,
        "result_sha256": sha(RAW / "result.json"),
        "pilot_result_sha256": sha(RAW / "trials/r0000/pilot-result.json"),
        "full_campaign_admitted": False,
        "reason": "shared v38 pilot entry overrode the path-aware agent; exact target was absent",
    }
    (RAW / "quality-audit.json").write_text(json.dumps(quality, indent=2, sort_keys=True) + "\n")
    (RAW / "remote-sha-index.json").write_bytes(REMOTE.read_bytes())
    members = {str(p.relative_to(RAW)): sha(p) for p in sorted(RAW.rglob("*"))
               if p.is_file() and p.name != ".campaign.lock"}
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    archive = ARCHIVES / f"{NAME}.tar.gz"
    manifest = ARCHIVES / f"{NAME}.members.json"
    receipt = ARCHIVES / f"{NAME}.receipt.json"
    if any(p.exists() for p in (archive, manifest, receipt)):
        raise RuntimeError("SOLR-34 v3 archive already exists")
    manifest.write_text(json.dumps({"schema_version": 1, "files": members},
                                   indent=2, sort_keys=True) + "\n")
    with tarfile.open(archive, "w:gz") as out:
        for name in sorted(members):
            out.add(RAW / name, arcname=f"{NAME}/{name}", recursive=False)
    with tarfile.open(archive, "r:gz") as saved:
        found = {}
        for item in saved:
            if item.isfile():
                name = item.name.removeprefix(f"{NAME}/")
                found[name] = hashlib.sha256(saved.extractfile(item).read()).hexdigest()
        if found != members:
            raise RuntimeError("archive member verification failed")
    data = {
        "schema_version": 1, "case_id": "SOLR-34", "kind": "healthy_only",
        "status": result["status"], "source_host": "node1",
        "source_path": remote["source"], "raw_local_path": str(RAW.relative_to(BASE)),
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "remote_file_count": len(remote["files"]),
        "remote_sha_index_sha256": sha(REMOTE),
        "result_sha256": sha(RAW / "result.json"),
        "quality_audit_sha256": sha(RAW / "quality-audit.json"),
        "archive_sha256": sha(archive), "manifest_sha256": sha(manifest),
        "member_count": len(members), "junit_1_0_0": True,
        "full_campaign_admitted": False,
    }
    receipt.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"receipt_sha256": sha(receipt), "archive_sha256": sha(archive),
                      "members": len(members)}, sort_keys=True))


if __name__ == "__main__":
    main()
