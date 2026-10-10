#!/usr/bin/env python3
"""GO-gated, case-local SOLR-34 fault bootstrap; no target-closure expansion."""

from __future__ import annotations

import argparse
import fcntl
import getpass
import hashlib
import json
import shutil
import socket
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4")
RELEASE = ROOT / "Mallory/dispatch/releases/815cba9b-target-absent-v1"
CONFIG = HERE / "config-full-node1.json"
REQUEST = HERE / "admission-request.json"
GO = HERE / "admission-bootstrap-node1.json"
OUT = ROOT / "data/mallory/solr34_fault_bootstrap_node1_v6/SOLR-34"
sys.path.insert(0, str(RELEASE))
from Mallory.core import campaign, scheduler  # noqa: E402
import bootstrap_policy as policy  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_loaded_catalog(rows: list[dict], config: dict) -> None:
    """Check every target ID against v5's actual loaded agent catalog."""
    expected = {
        ("DOOR_OBSERVED", policy.DOOR),
        ("TARGET_CHECK", policy.CHECK),
        ("TARGET_THROW", policy.RETHROW),
        ("TARGET_THROW", policy.NEW_THROW),
        ("REGION_ENTER", policy.REGION),
    }
    actual = [(row.get("type"), row.get("site")) for row in rows]
    if len(rows) != 5 or len(set(actual)) != 5 or set(actual) != expected:
        raise ValueError("loaded agent target/door catalog differs from exact five IDs")
    if (config["target"]["check_sites"] != [policy.CHECK]
            or config["target"]["throw_site"] != policy.NEW_THROW):
        raise ValueError("config target does not match loaded agent catalog")
    target_rows = [row for row in rows if row.get("class_name") ==
                   "org.apache.solr.servlet.CoordinatorHttpSolrCall"]
    door_rows = [row for row in rows if row.get("type") == "DOOR_OBSERVED"]
    if (len(target_rows) != 4 or len(door_rows) != 1
            or {row.get("bytecode_sha256") for row in target_rows} !=
            {config["expected_target_class_sha256"]}
            or door_rows[0].get("bytecode_sha256") !=
            config["mapping"]["solr_zk_client_class_sha256"]
            or door_rows[0].get("exception_class") != policy.TYPED
            or door_rows[0].get("resource_argument") != "first_string_parameter"
            or len({row.get("class_loader_id") for row in rows}) != 1):
        raise ValueError("loaded target class, typed door, or loader changed")


def preflight() -> dict:
    manifest = read(HERE / "sha-manifest.json")
    if manifest.get("case_id") != "SOLR-34" or manifest.get("stage") != "fault-bootstrap-node1-v6":
        raise ValueError("wrong case package")
    for name, pin in manifest["files"].items():
        path = HERE / name
        if not path.is_file() or path.stat().st_size != pin["bytes"] or sha(path) != pin["sha256"]:
            raise ValueError(f"case package changed: {name}")
    config, request, sites = read(CONFIG), read(REQUEST), read(HERE / "sites.json")
    catalog_fixture = HERE / "loaded-v5-sites.jsonl"
    provenance = read(HERE / "loaded-v5-catalog-provenance.json")
    if (sha(catalog_fixture) != config["mapping"]["v5_loaded_catalog_sha256"]
            or provenance.get("catalog_sha256") != sha(catalog_fixture)
            or provenance.get("agent_sha256") != config["mapping"]["agent_sha256"]
            or config["mapping"].get("v5_loaded_catalog_agent_sha256") !=
            config["mapping"]["agent_sha256"]
            or provenance.get("source_revision") != config["mapping"]["source_git_revision"]
            or provenance.get("junit_result") != {
                "status": "passed", "tests": 1, "failures": 0, "errors": 0, "skipped": 0}):
        raise ValueError("v5 loaded-agent catalog evidence changed")
    validate_loaded_catalog([json.loads(line) for line in
                             catalog_fixture.read_text().splitlines() if line.strip()], config)
    if (request.get("go") is not False or request.get("execution_status") != "not_launched"
            or request.get("case_id") != "SOLR-34" or request.get("host") != "node1"
            or request.get("mode") != "bounded_fault_bootstrap"
            or request.get("config_sha256") != sha(CONFIG)
            or request.get("runner_sha256") != sha(Path(__file__))
            or request.get("intended_output") != str(OUT)):
        raise ValueError("dispatch request changed")
    if (config.get("case_id") != "SOLR-34"
            or config.get("cluster_test") != "org.apache.solr.search.TestCoordinatorRole#testSimple"
            or config.get("core_release") != str(RELEASE)
            or not Path(campaign.__file__).resolve().is_relative_to(RELEASE)
            or config.get("site_file") != str(HERE / "sites.json")
            or config.get("command", [None, None])[1] != str(HERE / "run_pilot.py")
            or config.get("cwd") != str(SOURCE)
            or config.get("source_equivalent_root") != str(SOURCE)
            or config["target"]["check_sites"] != [policy.CHECK]
            or config["target"]["throw_site"] != policy.NEW_THROW
            or config.get("budget") != {"trials": 12, "seconds": 2400,
                                         "max_faults_per_trial": 2,
                                         "trial_timeout_seconds": 480}
            or config.get("candidate_replays") != 0
            or config.get("calibration_only") is not False
            or config.get("auto_promote_if_healthy") is not True
            or config.get("fault_types") != ["EXCEPTION"]
            or config.get("target_absent_bootstrap") != {
                "door_sites": [policy.DOOR], "max_trials": 12,
                "max_doors_per_trial": 6, "max_faults_per_trial": 2}
            or config.get("case_bootstrap", {}).get("resource") != policy.RESOURCE
            or config.get("case_bootstrap", {}).get("node") != policy.NODE
            or config.get("case_bootstrap", {}).get("epoch") != policy.EPOCH
            or config.get("case_bootstrap", {}).get("callbacks_excluded") is not True
            or config.get("admission", {}).get("full_promotion") is not False):
        raise ValueError("bounded bootstrap scope changed")
    expected_targets = {("org.apache.solr.servlet.CoordinatorHttpSolrCall", "getCore", line)
                        for line in (139, 140, 143)}
    if ({(row["clazz"], row["method"], row["line"]) for row in sites["targets"]}
            != expected_targets or len(sites["doors"]) != 1
            or sites["doors"][0].get("exception_class") != policy.TYPED
            or sites["doors"][0].get("method") != "lambda$getData$6"
            or sites["doors"][0].get("line") != 349):
        raise ValueError("exact target, rethrow, or typed door catalog changed")
    for artifact in config["runtime_artifacts"]:
        path = Path(artifact["path"])
        if not path.is_file() or sha(path) != artifact["sha256"]:
            raise ValueError(f"runtime artifact changed: {path}")
    agent = Path(config["agent_jar"])
    agent_manifest = Path(config["mapping"]["agent_build"]["release_manifest"])
    build = read(agent_manifest)
    if (sha(agent) != config["mapping"]["agent_sha256"]
            or sha(agent_manifest) != config["mapping"]["agent_build"]["release_manifest_sha256"]
            or build["agent_sha256"] != sha(agent)
            or config["env"]["MALLORY_SOLR_AGENT_JAR"] != str(agent)
            or "fault point.resource compared before FAULT_MATCHED or FAULT_APPLIED; mismatch leaves plan unconsumed"
            not in build["features"]):
        raise ValueError("case-local resource-match agent changed")
    for name, digest in build["source_sha256"].items():
        if sha(HERE / "agent-src" / name) != digest:
            raise ValueError(f"agent source changed: {name}")
    import run_pilot
    if run_pilot.AGENT != agent or run_pilot.SITES != HERE / "sites.json":
        raise ValueError("pilot agent or site binding changed")
    if (subprocess.check_output(["git", "-C", str(SOURCE), "rev-parse", "HEAD"],
                                text=True).strip() != config["mapping"]["source_git_revision"]
            or subprocess.check_output(["git", "-C", str(SOURCE), "status", "--porcelain"],
                                       text=True).strip()):
        raise ValueError("pinned Solr checkout changed")
    target = SOURCE / config["target"]["source_path"]
    test = SOURCE / "solr/core/src/test/org/apache/solr/search/TestCoordinatorRole.java"
    client = SOURCE / "solr/solrj/src/java/org/apache/solr/common/cloud/SolrZkClient.java"
    if (sha(target) != config["mapping"]["target_source_sha256"]
            or sha(test) != config["mapping"]["test_source_sha256"]
            or sha(client) != config["mapping"]["solr_zk_client_source_sha256"]):
        raise ValueError("target, JUnit, or client source changed")
    lines = target.read_text(encoding="utf-8").splitlines()
    if ("if (syntheticColl == null)" not in lines[137]
            or "if (createException != null)" not in lines[138]
            or "throw createException" not in lines[139]
            or "throw new SolrException" not in lines[142]
            or "keeper.getData(" not in client.read_text(encoding="utf-8").splitlines()[348]
            or "public void testSimple()" not in test.read_text(encoding="utf-8")):
        raise ValueError("source control flow changed")
    for jar_key, member, class_key, jar_sha_key in (
            ("compiled_jar", "org/apache/solr/servlet/CoordinatorHttpSolrCall.class",
             "compiled_class_sha256", "compiled_jar_sha256"),
            ("solrj_compiled_jar", "org/apache/solr/common/cloud/SolrZkClient.class",
             "solr_zk_client_class_sha256", "solrj_compiled_jar_sha256")):
        jar = Path(config["mapping"][jar_key])
        if sha(jar) != config["mapping"][jar_sha_key]:
            raise ValueError(f"compiled JAR changed: {jar}")
        with zipfile.ZipFile(jar) as archive:
            if hashlib.sha256(archive.read(member)).hexdigest() != config["mapping"][class_key]:
                raise ValueError(f"compiled class changed: {member}")
    campaign.validate_config(config)
    return {"config_sha256": sha(CONFIG), "runner_sha256": sha(Path(__file__)),
            "package_manifest_sha256": sha(HERE / "sha-manifest.json"),
            "core_manifest_sha256": sha(RELEASE / "manifest.json"),
            "agent_sha256": sha(agent), "intended_output": str(OUT)}


def check_go(path: Path, metadata: dict) -> str:
    if path.resolve() != GO:
        raise ValueError("case-local node1 GO receipt required")
    receipt = read(path)
    expected = {"go": True, "host": "node1", "case_id": "SOLR-34",
                "mode": "bounded_fault_bootstrap",
                "config_sha256": metadata["config_sha256"],
                "runner_sha256": metadata["runner_sha256"],
                "intended_output": str(OUT)}
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ValueError("dispatch GO receipt absent or mismatched")
    return sha(path)


def install_policy() -> None:
    original_analyze = campaign.analyze
    original_mutate = campaign.mutate
    original_trial = campaign._run_trial
    original_apply = campaign._apply_result

    def analyze(trace, target, plan, **kwargs):
        return policy.annotate_feedback(list(trace.events),
                                        original_analyze(trace, target, plan, **kwargs), plan)

    def mutate(parent, feedback, config, *, bootstrap=False):
        return policy.mutate(parent, feedback, config, original_mutate,
                             scheduler.sequence_signature, bootstrap=bootstrap)

    def run_trial(config, out, trial_id, plan, save_running, target_binding):
        result = original_trial(config, out, trial_id, plan, save_running, target_binding)
        trial = out / "trials" / f"r{trial_id:04d}"
        try:
            rows = policy.load_events(trial)
            catalog = [json.loads(line) for line in (trial / "sites.jsonl").read_text().splitlines()
                       if line.strip()]
            audit = policy.audit_trial(rows, plan, catalog)
        except (OSError, ValueError, KeyError) as exc:
            audit = {"valid": False, "status": "audit_input_unavailable", "detail": str(exc)}
        result["case_audit"] = audit
        if not audit["valid"]:
            result["feedback"]["all_faults_effective"] = False
            result["feedback"]["target_exception_candidate"] = False
            result["feedback"]["status"] = "case_gate_failed"
        campaign.atomic_json(trial / "result.json", result)
        return result

    def apply_result(state, config, result, item):
        original_apply(state, config, result, item)
        audit = result.get("case_audit", {})
        if result["trial_id"] > 0 and audit.get("valid") and audit.get("target_after_fault"):
            state["status"] = "exact_target_observed_for_source_review"
            state["queue"].clear()

    campaign.analyze = analyze
    campaign.mutate = mutate
    campaign._run_trial = run_trial
    campaign._apply_result = apply_result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("bounded_fault_bootstrap",), required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    metadata = preflight()
    if args.preflight_only:
        print(json.dumps({"preflight": "passed_static_only", "go": False,
                          "case_id": "SOLR-34", **metadata}, sort_keys=True))
        return 0
    if args.admission_receipt is None:
        parser.error("dispatch GO receipt required before starting a JVM")
    metadata["admission_sha256"] = check_go(args.admission_receipt, metadata)
    if socket.gethostname().split(".", 1)[0] != "node1":
        raise ValueError("node1 required")
    lock_root = Path("/tmp/mallory-lanes")
    lock_root.mkdir(parents=True, exist_ok=True)
    handles = []
    try:
        for name in ("zookeeper-node1-source.lock", "solr-node1-v1.lock",
                     "solr-source-graphchecker-8.11.4.lock"):
            handle = (lock_root / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles.append(handle)
        if OUT.exists():
            checkpoint = OUT / "checkpoint.json"
            saved_config = OUT / "config.json"
            if (not checkpoint.is_file() or not saved_config.is_file()
                    or read(checkpoint).get("config_digest") !=
                    campaign.digest(read(CONFIG))
                    or sha(saved_config) != sha(CONFIG)):
                raise ValueError("existing output is not this exact resumable campaign")
        if shutil.disk_usage(ROOT).free < 7_650_410_496:
            raise ValueError("7,650,410,496 free bytes required")
        available = next(int(row.split()[1]) for row in Path("/proc/meminfo").read_text().splitlines()
                         if row.startswith("MemAvailable:"))
        if available < 8_388_608:
            raise ValueError("8,388,608 KiB MemAvailable required")
        processes = subprocess.check_output(["ps", "-eo", "user=,comm="], text=True)
        if any(row.split() == [getpass.getuser(), "java"] for row in processes.splitlines()):
            raise ValueError("another user JVM is running on node1")
        install_policy()
        print(json.dumps({"preflight": "passed", "mode": args.mode,
                          **metadata}, sort_keys=True), flush=True)
        state = campaign.run(CONFIG, OUT, calibration_only=False)
    finally:
        for handle in reversed(handles):
            handle.close()
    print(json.dumps({"status": state["status"],
                      "completed_trials": state["completed_trials"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
