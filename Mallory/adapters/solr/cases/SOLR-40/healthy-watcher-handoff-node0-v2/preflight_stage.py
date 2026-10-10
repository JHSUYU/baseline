#!/usr/bin/env python3
"""No-JVM verification of the SOLR-40 exact-reference handoff stage."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
V1 = ROOT / "data/mallory/calibration_solr40_watcher_handoff_v1_node0/SOLR-40"
SOURCE = ROOT / "Mallory/instrumentation/src/main/java/edu/uva/liftlab/mallory/instrumentation"
HASHES = {
    SOURCE / "Probe.java": "8f6ac5f38f10ba05cf20e3455adfe9d06bcc008ebce3d8436a92c9ff471b10f0",
    SOURCE / "MalloryTransformer.java": "099c49324885f0be270b82ec41ee43fda89384a7203263ff747e36cb058fe5f5",
    V1 / "trials/r0000/events.jsonl.gz": "fe08a7a13738db66b4fb4df961a384bdfa86307f4ce70419743232a014b41cef",
    V1 / "trials/r0000/result.json": "8ed806fb29206e3140cd99e6dc55f7442f849afc0f5b21260608ae02ebfd99a5",
    V1 / "trials/r0000/junit.log": "81d8cbc7d8cde4a5739347bbff3c64ae6165ec281f317c2f0bd4807e16b38f7b",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    for path, digest in HASHES.items():
        if not path.is_file() or sha(path) != digest:
            raise ValueError(f"pinned source/evidence changed: {path}")
    request = json.loads((HERE / "admission-request.json").read_text())
    config = json.loads((HERE / "config.staged.json").read_text())
    if not (request["go"] is False and request["full_campaign_go"] is False and
            config["calibration_only"] is True and
            config["auto_promote_if_healthy"] is False and
            config["budget"]["trials"] == 1 and
            config["admission"]["full_promotion"] is False and
            config["require_event_time_paths"] is True and
            config["reject_coarse_roots"] is True and
            config["allow_local_timeline_doors"] is False and
            config["agent_jar"] == str(HERE / "releases/mallory-agent.jar") and
            config["mapping"]["agent_sha256"] == "PENDING_ISOLATED_RELEASE" and
            not (HERE / "releases/mallory-agent.jar").exists()):
        raise ValueError("v2 is not an unbuilt, healthy-only stage")
    subprocess.run(["git", "apply", "--check", str(HERE / "exact-reference-field.patch")],
                   cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run([sys.executable, "-m", "unittest", "-q", str(HERE / "test_stage.py")],
                   cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    receipt = json.loads((HERE / "v1-gap-receipt.json").read_text())
    if not (receipt["source_trace_sha256"] == HASHES[V1 / "trials/r0000/events.jsonl.gz"] and
            receipt["source_trial_result_sha256"] == HASHES[V1 / "trials/r0000/result.json"] and
            receipt["observed_event_time_paths"] == [] and
            receipt["candidate_paths_with_sampled_state"] > 0 and
            receipt["full_campaign_go"] is False):
        raise ValueError("v1 gap receipt no longer supports the v2 source stage")
    print(json.dumps({"case_id": "SOLR-40", "status": "offline_stage_passed",
                      "jvm_run": False, "healthy_only": True, "agent_release_built": False,
                      "candidate_paths": receipt["candidate_paths_with_sampled_state"],
                      "full_campaign_go": False}, sort_keys=True))


if __name__ == "__main__":
    main()
