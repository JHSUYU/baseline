#!/usr/bin/env python3
"""Pin ZK13 to a nonthrowing, observed connect-request cluster workload."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil


TARGET_SOURCE = "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/ReadOnlyZooKeeperServer.java"
TEST_SOURCE = "zookeeper-server/src/test/java/org/apache/zookeeper/test/ReadOnlyModeTest.java"
TARGET_CLASS = "zookeeper-server/target/classes/org/apache/zookeeper/server/quorum/ReadOnlyZooKeeperServer.class"
SELECTOR = "ReadOnlyModeTest#testConnectionEvents"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(ok: bool, why: str) -> None:
    if not ok:
        raise ValueError(why)


def prepare(template_path: Path, healthy_path: Path, receipt_path: Path,
            agent_path: Path, output_path: Path, trials: int, seconds: int) -> None:
    require(trials > 0 and seconds > 0, "budget must be positive")
    template = json.loads(template_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    attestation_path = healthy_path / "workload-attestation.json"
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    command = json.loads((healthy_path / "command.json").read_text(encoding="utf-8"))
    source = Path(receipt["patched_root"]).resolve()
    require(template["case_id"] == command["case_id"] == attestation["case_id"] ==
            "ZOOKEEPER-13", "case identity drift")
    require(command["candidate_selector"] == SELECTOR and
            command["cwd"] == str(source) and
            attestation["selector"] == SELECTOR and
            attestation["status"] == "alternate_healthy_guard_reached" and
            attestation["target_check_count"] > 0 and
            attestation["target_throw_count"] == 0 and
            attestation["observed_path_door_count"] > 0 and
            attestation["target_nodes"] and
            attestation["target_outcome_counts"] == {"TAKEN": attestation["target_check_count"]},
            "selected alternate lacks a named, nonthrowing observed path")
    require(all(edge["kind"] == "region_parent"
                for edge in attestation["observed_path_edges"]),
            "connect-request path contains an unobserved edge")
    require(attestation["overlay_receipt_sha256"] == sha(receipt_path) and
            attestation["agent_jar_sha256"] == sha(agent_path),
            "healthy source receipt or agent changed")
    class_file = source / TARGET_CLASS
    class_sha = sha(class_file)
    require(class_sha == attestation["loaded_target_class_sha256"] and
            any(row.get("path") == str(class_file) and row.get("sha256") == class_sha
                for row in receipt["compiled_artifacts"]),
            "target class differs from healthy loaded bytes")
    require(sha(source / TARGET_SOURCE) == receipt["modified_files"][TARGET_SOURCE] and
            sha(source / TEST_SOURCE) == receipt["test_sources"][TEST_SOURCE] and
            attestation["target_source_sha256"] == sha(source / TARGET_SOURCE) and
            attestation["test_source_sha256"] == sha(source / TEST_SOURCE),
            "source differs from healthy attestation or overlay receipt")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    site_file = output_path.with_suffix(".sites.json")
    shutil.copyfile(healthy_path / "sites.json", site_file)
    check_sites = attestation["target_guard_sites"]
    throw_site = attestation["target_throw_site"]
    require(check_sites == ["org.apache.zookeeper.server.quorum.ReadOnlyZooKeeperServer#"
                            f"validateSession(Lorg/apache/zookeeper/server/ServerCnxn;J)V@"
                            f"{command['target_guard_line']}:branch:1"] and
            throw_site.endswith(f"@{command['target_throw_line']}:throw:1"),
            "exact sites differ from compiled healthy catalog")
    template["cluster_test"] = "org.apache.zookeeper.test." + SELECTOR
    template["command"] = [
        "mvn", "-pl", "zookeeper-server", "-am", f"-Dtest={SELECTOR}",
        "-Dsurefire.failIfNoSpecifiedTests=false",
        "-Dmallory.test.dir={trial_dir}/test-data", "test",
    ]
    template["cwd"] = str(source)
    template["site_file"] = str(site_file)
    template["agent_jar"] = str(agent_path)
    template["agent_properties"].update({"state.fields": False, "state.maps": False})
    template["target"].update(check_sites=check_sites, throw_site=throw_site,
                              source_line=command["target_throw_line"])
    template["expected_target_class_sha256"] = class_sha
    template["source_overlay_receipt"] = str(receipt_path)
    template["source_overlay_receipt_sha256"] = sha(receipt_path)
    template["budget"].update(trials=trials, seconds=seconds,
                              trial_timeout_seconds=180, max_faults_per_trial=6)
    template["calibration_only"] = False
    template["auto_promote_if_healthy"] = True
    template["mapping"].update(
        source_root=str(source),
        compiled_artifact=str(source / "zookeeper-server/target/classes"),
        compiled_class_sha256=class_sha,
        target_source_sha256=sha(source / TARGET_SOURCE),
        test_source_sha256=sha(source / TEST_SOURCE),
        test_source_path=TEST_SOURCE,
        target_class_relative=TARGET_CLASS,
        agent_sha256=sha(agent_path),
        healthy_seed_verified=True,
        status="connectpath_healthy_attested_pending_campaign_seed",
        connectpath_healthy_attestation=str(attestation_path),
        connectpath_healthy_attestation_sha256=sha(attestation_path),
    )
    template["mapping"]["verified_healthy_probe"] = {
        "scope": "independent_connect_request_target_path_proof",
        "evidence": str(attestation_path), "evidence_sha256": sha(attestation_path),
        "target_source_sha256": sha(source / TARGET_SOURCE),
        "class_sha256": class_sha, "check_sites": check_sites,
        "throw_site": throw_site,
        "observed_path_door_count": attestation["observed_path_door_count"],
    }
    template["runtime_artifacts"] = [
        {"path": str(agent_path), "sha256": sha(agent_path)},
        {"path": str(site_file), "sha256": sha(site_file)},
    ]
    require(template["agent_transport"] == "surefire_argline" and
            template["agent_arg_property"] == "mallory.agent.arg",
            "campaign agent transport differs from healthy command")
    output_path.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("template", type=Path)
    parser.add_argument("healthy_evidence", type=Path)
    parser.add_argument("source_receipt", type=Path)
    parser.add_argument("agent_jar", type=Path)
    parser.add_argument("output_config", type=Path)
    parser.add_argument("--trials", type=int, default=8)
    parser.add_argument("--seconds", type=int, default=900)
    args = parser.parse_args()
    prepare(args.template.resolve(), args.healthy_evidence.resolve(),
            args.source_receipt.resolve(), args.agent_jar.resolve(),
            args.output_config.resolve(), args.trials, args.seconds)
