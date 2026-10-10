#!/usr/bin/env python3
"""Read-only preflight for the future SOLR-40 v3 healthy JUnit trial."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
V2 = HERE.parent / "healthy-watcher-handoff-node0-v2"
V2_RAW = ROOT / "data/mallory/calibration_solr40_reference_handoff_v2_node0/SOLR-40"
PINNED = ROOT / "Mallory/adapters/solr/cases/SOLR-13/runtime-role-v1/work"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def main() -> dict:
    manifest = json.loads((HERE / "release-manifest.json").read_text())
    config_path = HERE / "config.json"
    config = json.loads(config_path.read_text())
    release = HERE / "releases/mallory-agent.jar"
    prior = subprocess.run(
        [sys.executable, str(V2 / "run_healthy_v2.py"), "--preflight-only"],
        cwd=ROOT, capture_output=True, text=True, check=True)
    require(json.loads(prior.stdout.splitlines()[-1])["status"] ==
            "offline_runtime_preflight_passed", "v2 release preflight failed")
    require(sha(V2 / "release-manifest.json") == manifest["v2_release_manifest_sha256"],
            "v2 release manifest changed")
    for relative, digest in manifest["v2_raw_sha256"].items():
        path = V2_RAW / relative
        require(path.is_file() and sha(path) == digest,
                f"sealed v2 evidence changed: {relative}")
    require(config["case_id"] == "SOLR-40" and
            config["revision"] == "SOLR-40-healthy-exact-reference-handoff-node0-v3" and
            config["calibration_only"] is True and
            config["auto_promote_if_healthy"] is False and
            config["budget"]["trials"] == 1 and
            config["admission"]["full_promotion"] is False and
            config["require_event_time_paths"] is True and
            config["reject_coarse_roots"] is True and
            config["allow_local_timeline_doors"] is False and
            config["command"][1] == str(HERE / "run_pilot.py") and
            config["agent_jar"] == str(release) and
            config["env"]["MALLORY_SOLR_AGENT_JAR"] == str(release) and
            config["site_file"] == str(HERE / "sites.json"),
            "v3 future healthy-only policy or recognized runner changed")
    require(sha(config_path) == manifest["config_sha256"] and
            sha(release) == manifest["agent_jar_sha256"] ==
            config["mapping"]["agent_sha256"] and
            sha(release) == sha(V2 / "releases/mallory-agent.jar") and
            sha(HERE / "sites.json") == manifest["sites_sha256"] and
            sha(HERE / "run_pilot.py") == manifest["pilot_runner_sha256"] and
            sha(HERE / "run_healthy_v3.py") == manifest["healthy_runner_sha256"] and
            sha(HERE / "gate_v2.py") == manifest["gate_sha256"] and
            sha(HERE / "call_return.py") == manifest["call_return_sha256"] and
            sha(HERE / "audit_v2.py") == manifest["post_audit_sha256"] and
            sha(HERE / "test_runner_recognition.py") == manifest["recognition_test_sha256"],
            "v3 package digest changed")
    request = json.loads((HERE / "admission-request.json").read_text())
    require(request.get("go") is False and request.get("full_campaign_go") is False and
            request.get("case_id") == "SOLR-40" and
            request.get("host") == "node0" and request.get("mode") == "healthy" and
            request.get("config_sha256") == sha(config_path) and
            request.get("agent_jar_sha256") == sha(release) and
            request.get("runner_sha256") == sha(HERE / "run_healthy_v3.py") and
            request.get("admission_receipt") == str(HERE / "admission-healthy-node0.json") and
            request.get("intended_output") == str(
                ROOT / "data/mallory/calibration_solr40_reference_handoff_v3_node0/SOLR-40") and
            sha(HERE / "admission-request.json") == manifest["admission_request_sha256"],
            "v3 healthy-only admission request changed")
    for artifact in config["runtime_artifacts"]:
        path = Path(artifact["path"])
        require(path.is_file() and sha(path) == artifact["sha256"],
                f"v3 runtime artifact changed: {path}")
    sys.path.insert(0, str(PINNED))
    from Mallory.core import campaign  # noqa: E402
    from Mallory.core.junit import collect_junit_receipt, runner_kind  # noqa: E402
    require(Path(campaign.__file__).resolve().is_relative_to(PINNED),
            "campaign core is not pinned")
    campaign.validate_config(config)
    require(runner_kind(config["command"]) == "solr_junit_wrapper",
            "v3 runner is not recognized by pinned core")
    prior_result = json.loads((V2_RAW / "trials/r0000/result.json").read_text())
    require(prior_result["return_code"] == 0 and prior_result["timed_out"] is False,
            "v2 source trial did not exit cleanly")
    junit = collect_junit_receipt(V2_RAW / "trials/r0000", config["command"],
                                  Path(config["cwd"]), 0, None,
                                  config["cluster_test"])
    require(junit["status"] == "passed" and junit["tests"] == 1 and
            junit["failures"] == junit["errors"] == junit["skipped"] == 0,
            "v2 raw JUnit would not pass with recognized v3 entrypoint")
    receipt = {"case_id": "SOLR-40", "status": "offline_v3_runner_recognized",
               "v2_raw_junit_counts": {key: junit[key] for key in
                                       ("tests", "failures", "errors", "skipped")},
               "config_sha256": sha(config_path), "agent_jar_sha256": sha(release),
               "junit_launched": False, "healthy_only": True, "full_campaign_go": False}
    print(json.dumps(receipt, sort_keys=True))
    return receipt


if __name__ == "__main__":
    main()
