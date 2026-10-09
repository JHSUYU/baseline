#!/usr/bin/env python3
"""Pin a source-attested ZooKeeper cluster JUnit for one core healthy seed."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from Mallory.adapters.zookeeper.attest_selected_calibration import CASES


BASE = Path("/users/ZhenyuLi/baseline")
SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/zookeeper-connectpath-lane2")
AGENT = BASE / "data/mallory/calibration/agent-builds/mallory-agent-causal-context-bf8e6dba.jar"
RECEIPT = BASE / "Mallory/adapters/zookeeper/zookeeper-3.8.7-connectpath-lane2-overlay.json"
CORE_5820 = "5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf"
CORE_LOCAL = "5a35547d57dd66c29b15260f04cf52941b907e28bc07f0ceb0f1d4b3782c4040"
STANDALONE = {"ZOOKEEPER-04": "reconnect-healthy-v1",
              "ZOOKEEPER-05": "rolling-healthy-v1", "ZOOKEEPER-07": "rolling-healthy-v1",
              "ZOOKEEPER-11": "epoch-file-healthy-v1", "ZOOKEEPER-12": "epoch-file-healthy-v1"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(case: str, out: Path, *, local_timeline: bool) -> None:
    assert local_timeline == (case in {"ZOOKEEPER-04", "ZOOKEEPER-11", "ZOOKEEPER-12"})
    core_id = CORE_LOCAL if local_timeline else CORE_5820
    core = BASE / "Mallory/dispatch/releases" / core_id
    assert (core / "manifest.json").is_file()
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    evidence = BASE / "data/mallory/calibration" / case / STANDALONE[case]
    attestation_path = evidence / "attestation.json"
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    pins = json.loads((evidence / "pins.json").read_text(encoding="utf-8"))
    spec = CASES[case]
    assert attestation["case_id"] == case and attestation["target_check_count"] > 0
    assert attestation["target_throw_count"] == 0 and attestation["target_nodes"]
    if not local_timeline:
        assert attestation["status"] == "healthy_closure_proven"
        assert attestation["observed_path_door_count"] > 0
    assert pins["source_overlay_receipt_sha256"] == sha(RECEIPT)
    assert pins["agent_sha256"] == sha(AGENT)
    target_source = SOURCE / spec["target_source"]
    test_source = SOURCE / spec["test_source"]
    compiled = SOURCE / spec["compiled_class"]
    assert receipt["patched_root"] == str(SOURCE)
    assert sha(target_source) == pins["target_source_sha256"]
    assert sha(test_source) == pins["test_source_sha256"]
    assert sha(compiled) == pins["loaded_class_expected_sha256"]
    assert any(row["path"] == str(compiled) and row["sha256"] == sha(compiled)
               for row in receipt["compiled_artifacts"])
    assert attestation["target_guard_site"].startswith(
        spec["method"] + f"@{spec['guard_line']}:")
    assert attestation["target_throw_site"] == spec["method"] + f"@{spec['throw_line']}:throw:1"

    template = json.loads((BASE / "Mallory/cases" / f"{case}.json").read_text(encoding="utf-8"))
    assert template["case_id"] == case
    out.parent.mkdir(parents=True, exist_ok=True)
    assert not out.exists()
    site_file = out.with_suffix(".sites.json")
    assert not site_file.exists()
    shutil.copyfile(evidence / "sites.json", site_file)
    template.update(
        calibration_only=True, auto_promote_if_healthy=False,
        allow_local_timeline_doors=local_timeline,
        core_release=str(core), cwd=str(SOURCE), agent_jar=str(AGENT),
        agent_transport="surefire_argline", agent_arg_property="mallory.agent.arg",
        site_file=str(site_file), expected_target_class_sha256=sha(compiled),
        source_overlay_receipt=str(RECEIPT), source_overlay_receipt_sha256=sha(RECEIPT),
        cluster_test=spec["test_class"] + "#" + spec["selector"].split("#", 1)[1],
        command=["mvn", "-pl", "zookeeper-server", "-am",
                 f"-Dtest={spec['selector']}", "-Dsurefire.failIfNoSpecifiedTests=false",
                 "-Dmallory.test.dir={trial_dir}/test-data", "test"],
    )
    template["agent_properties"].update({"auto.io.doors": True,
                                          "state.fields": False, "state.maps": False})
    template["target"].update(check_sites=[attestation["target_guard_site"]],
                              throw_site=attestation["target_throw_site"],
                              source_line=spec["throw_line"])
    if case in {"ZOOKEEPER-04", "ZOOKEEPER-11", "ZOOKEEPER-12"}:
        template["target"]["nodes"] = ["zk2"] if case == "ZOOKEEPER-04" else ["zk0"]
    else:
        template["target"].pop("nodes", None)
    template["budget"].update(trials=80, seconds=3600,
                              max_faults_per_trial=6, trial_timeout_seconds=180)
    template["mapping"].update(
        status="standalone_target_attested_pending_fresh_core_seed",
        source_root=str(SOURCE),
        compiled_artifact=str(SOURCE / "zookeeper-server/target/classes"),
        compiled_class_sha256=sha(compiled), target_source_sha256=sha(target_source),
        test_source_sha256=sha(test_source), test_source_path=spec["test_source"],
        target_class_relative=spec["compiled_class"], agent_sha256=sha(AGENT),
        healthy_seed_verified=False,
        verified_healthy_probe={"scope": "standalone_existing_cluster_junit_calibration",
                                "evidence": str(attestation_path),
                                "evidence_sha256": sha(attestation_path),
                                "target_class_sha256": sha(compiled),
                                "target_check_site": attestation["target_guard_site"],
                                "target_throw_site": attestation["target_throw_site"]},
    )
    template["runtime_artifacts"] = [
        {"path": str(AGENT), "sha256": sha(AGENT)},
        {"path": str(site_file), "sha256": sha(site_file)},
    ]
    assert template["agent_transport"] == "surefire_argline"
    assert template["agent_arg_property"] == "mallory.agent.arg"
    out.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("case_id", choices=sorted(STANDALONE))
    parser.add_argument("output_config", type=Path)
    parser.add_argument("--local-timeline", action="store_true")
    args = parser.parse_args()
    prepare(args.case_id, args.output_config, local_timeline=args.local_timeline)
