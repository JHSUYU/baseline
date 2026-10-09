#!/usr/bin/env python3
"""Pin a ZK02/ZK03 fault campaign to an independently proved request path."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil


TARGET_CLASS = "zookeeper-server/target/classes/org/apache/zookeeper/server/SessionTrackerImpl.class"
TARGET_SOURCE = "zookeeper-server/src/main/java/org/apache/zookeeper/server/SessionTrackerImpl.java"
TEST_SOURCE = "zookeeper-server/src/test/java/org/apache/zookeeper/test/QuorumTest.java"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(value: bool, reason: str) -> None:
    if not value:
        raise ValueError(reason)


def prepare(template_path: Path, evidence_dir: Path, receipt_path: Path,
            agent_path: Path, output_path: Path, trials: int, seconds: int) -> None:
    require(trials > 0 and seconds > 0, "budget must be positive")
    template = json.loads(template_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    attestation_path = evidence_dir / "causal-path-attestation.json"
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    command = json.loads((evidence_dir / "command.json").read_text(encoding="utf-8"))
    source = Path(receipt["patched_root"]).resolve()
    case = template["case_id"]
    require(case in {"ZOOKEEPER-02", "ZOOKEEPER-03"} and
            attestation["case_id"] == command["case_id"] == case,
            "case identity drift")
    require(attestation["status"] == "healthy_causal_path_proven" and
            attestation["target_throw_count"] == 0 and
            attestation["pretarget_in_closure_doors"] > 0,
            "healthy seed has no proved pretarget client I/O path")
    witness = attestation["observed_witness"]
    expected_door = ("zookeeper.client.connect.read" if case == "ZOOKEEPER-03" and
                     "connect_path" in receipt else "zookeeper.client.request.read")
    require(witness["door_site"] == expected_door and
            {"task", "region_parent"}.issubset({edge["kind"] for edge in witness["edges"]}),
            "healthy seed has no observed request handoff into the target")
    if "request_path" in receipt:
        rpc = attestation.get("exact_quorum_request_rpc")
        require(isinstance(rpc, dict) and
                "rpc" in {edge["kind"] for edge in witness["edges"]} and
                isinstance(rpc.get("request_port"), str) and
                rpc["request_port"].startswith("REQUEST:"),
                "healthy seed has no exact follower-to-leader request RPC")
    require(command["cwd"] == str(source) and
            command["candidate_selector"] == "QuorumTest#testMultiToFollower",
            "healthy workload or source drift")
    require(attestation["overlay_receipt_sha256"] == sha(receipt_path) and
            attestation["agent_jar_sha256"] == sha(agent_path),
            "healthy seed used different source receipt or agent bytes")
    class_file = source / TARGET_CLASS
    class_sha = sha(class_file)
    require(class_sha == attestation["loaded_target_class_sha256"] and
            any(row.get("path") == str(class_file) and row.get("sha256") == class_sha
                for row in receipt["compiled_artifacts"]),
            "compiled target differs from healthy loaded class or receipt")
    require(sha(source / TARGET_SOURCE) == receipt["modified_files"][TARGET_SOURCE] and
            sha(source / TEST_SOURCE) == receipt["test_sources"][TEST_SOURCE],
            "target or JUnit source differs from receipt")
    require(template["cluster_test"] == "org.apache.zookeeper.test.QuorumTest#testMultiToFollower",
            "template workload changed")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    site_file = output_path.with_suffix(".sites.json")
    shutil.copyfile(evidence_dir / "sites.json", site_file)
    locations = command["target_locations"][case]
    check_sites = attestation.get("exact_check_sites", [attestation["exact_check_site"]])
    throw_site = attestation["exact_throw_site"]
    expected_branches = (4,) if case == "ZOOKEEPER-02" else (1, 2)
    require(check_sites == [f"org.apache.zookeeper.server.SessionTrackerImpl#"
                            f"{'checkSession' if case == 'ZOOKEEPER-02' else 'setOwner'}"
                            f"(JLjava/lang/Object;)V@{locations['target_guard_line']}:branch:{branch}"
                            for branch in expected_branches] and
            throw_site.endswith(f"@{locations['target_throw_line']}:throw:1"),
            "exact healthy site disagrees with source location")
    test_data_arg = "-Dmallory.test.dir={trial_dir}/test-data"
    if test_data_arg not in template["command"]:
        require(template["command"][-1] == "test", "unexpected Maven command")
        template["command"].insert(-1, test_data_arg)
    template["cwd"] = str(source)
    template["site_file"] = str(site_file)
    template["agent_jar"] = str(agent_path)
    # Field reads are sampled candidate edges. The proof and campaign must
    # stand on the observed client/request handoff without their trace cost.
    template["agent_properties"]["state.fields"] = False
    template["target"]["check_sites"] = check_sites
    template["target"]["throw_site"] = throw_site
    template["target"]["source_line"] = locations["target_throw_line"]
    template["expected_target_class_sha256"] = class_sha
    template["source_overlay_receipt"] = str(receipt_path)
    template["source_overlay_receipt_sha256"] = sha(receipt_path)
    template["budget"].update(trials=trials, seconds=seconds)
    template["budget"]["trial_timeout_seconds"] = 180
    template["calibration_only"] = False
    template["auto_promote_if_healthy"] = True
    template["mapping"].update(
        source_root=str(source),
        compiled_artifact=str(source / "zookeeper-server/target/classes"),
        compiled_class_sha256=class_sha,
        target_source_sha256=sha(source / TARGET_SOURCE),
        test_source_sha256=sha(source / TEST_SOURCE),
        agent_sha256=sha(agent_path),
        healthy_seed_verified=True,
        status="epochfix_causal_path_proven_pending_campaign_seed",
        epochfix_healthy_attestation=str(attestation_path),
        epochfix_healthy_attestation_sha256=sha(attestation_path),
    )
    template["mapping"]["verified_healthy_probe"] = {
        "scope": "independent_epochfix_healthy_path_proof",
        "evidence": str(attestation_path),
        "evidence_sha256": sha(attestation_path),
        "target_source_sha256": sha(source / TARGET_SOURCE),
        "class_sha256": class_sha,
        "check_sites": check_sites,
        "throw_site": throw_site,
    }
    template["runtime_artifacts"] = [
        {"path": str(agent_path), "sha256": sha(agent_path)},
        {"path": str(site_file), "sha256": sha(site_file)},
    ]
    require("-Dmallory.test.dir={trial_dir}/test-data" in template["command"] and
            template["agent_transport"] == "surefire_argline" and
            template["agent_arg_property"] == "mallory.agent.arg",
            "campaign test data or Surefire agent transport is not isolated")
    output_path.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("template", type=Path)
    parser.add_argument("healthy_evidence", type=Path)
    parser.add_argument("epochfix_receipt", type=Path)
    parser.add_argument("agent_jar", type=Path)
    parser.add_argument("output_config", type=Path)
    parser.add_argument("--trials", type=int, default=8)
    parser.add_argument("--seconds", type=int, default=900)
    args = parser.parse_args()
    prepare(args.template.resolve(), args.healthy_evidence.resolve(),
            args.epochfix_receipt.resolve(), args.agent_jar.resolve(),
            args.output_config.resolve(), args.trials, args.seconds)
