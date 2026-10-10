#!/usr/bin/env python3
"""Pinned, GO-gated SOLR-15 path-aware healthy observation on node0."""

from __future__ import annotations

import argparse
import copy
import fcntl
import getpass
import json
import shutil
import socket
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
V2 = HERE.parent / "chaos-healthy-node0-v2"
ORIGINAL = HERE.parent / "chaos-target-discovery-v1"
RELEASE = ROOT / ("Mallory/instrumentation/releases/"
                  "b4bb6493699d87dceb966ff63b6f727455e5afdbbe1ddce4cd2247faab17eae4")
OUT = ROOT / "data/mallory/solr15_path_healthy_node0_v3/healthy"
sys.path.insert(0, str(ORIGINAL.parents[2]))
from fault_discovery_runner import campaign, read, sha  # noqa: E402


def _release_check() -> dict:
    manifest = read(RELEASE / "manifest.json")
    if (manifest.get("agent_sha256") != RELEASE.name
            or sha(RELEASE / "mallory-agent.jar") != RELEASE.name
            or manifest.get("solrj_class_sha256") !=
            "51b3131fed142509b80da408d0d3f8d036045237b51a48c2a4dd9cf574a72dc0"
            or manifest.get("test_results") !=
            {"tests": 26, "failures": 0, "errors": 0, "skipped": 0}):
        raise ValueError("path-aware agent release changed")
    source = ROOT / manifest["source_root"]
    for name, digest in manifest["source_sha256"].items():
        if sha(source / name) != digest:
            raise ValueError("path-aware agent source changed: " + name)
    transformer = (source / "src/main/java/edu/uva/liftlab/mallory/"
                   "instrumentation/MalloryTransformer.java").read_text()
    probe = (source / "src/main/java/edu/uva/liftlab/mallory/"
             "instrumentation/Probe.java").read_text()
    if ("isSolrZkResourceDoor" not in transformer
            or 'doorSite.put("resource_argument", "first_string_parameter")' not in transformer
            or '"resource", resource' not in probe):
        raise ValueError("path observation is absent from pinned agent source")
    return {"agent_sha256": RELEASE.name,
            "agent_manifest_sha256": sha(RELEASE / "manifest.json")}


def preflight() -> dict:
    # The v2 gate pins the unchanged chaos JUnit, source revision, exact target,
    # v38 adapter, site catalog and target-absent controller release.
    sys.path.insert(0, str(V2))
    import run_campaign as v2_runner  # noqa: E402
    v2_runner.preflight()
    release = _release_check()
    config_path = HERE / "config-healthy-node0.json"
    config = read(config_path)
    expected = copy.deepcopy(read(V2 / "config-healthy-node0.json"))
    old_agent = expected["agent_jar"]
    new_agent = str(RELEASE / "mallory-agent.jar")
    expected["agent_jar"] = new_agent
    expected["env"]["MALLORY_SOLR_AGENT_JAR"] = new_agent
    expected["mapping"]["agent_sha256"] = RELEASE.name
    expected["mapping"]["agent_build"] = {
        "artifact": new_agent,
        "source_root": "Mallory/instrumentation/experiments/solr-zk-resource-v1",
        "release_manifest": str(RELEASE / "manifest.json")}
    expected["mapping"]["door_status"] = (
        "path_aware_retry_internal_native_exists_pending_fresh_healthy")
    expected["revision"] = "SOLR-15-path-aware-healthy-node0-v3"
    for row in expected["runtime_artifacts"]:
        if row["path"] == old_agent:
            row.update(path=new_agent, sha256=RELEASE.name)
        elif row["path"] == str(Path(old_agent).with_name("manifest.json")):
            row.update(path=str(RELEASE / "manifest.json"),
                       sha256=release["agent_manifest_sha256"])
    if config != expected:
        raise ValueError("path-aware healthy config differs from pinned v2 seed")
    campaign.validate_config(config)

    package = read(HERE / "sha-manifest.json")
    if (package.get("case_id") != "SOLR-15"
            or package.get("agent_release_sha256") != RELEASE.name
            or package.get("v2_manifest_sha256") != sha(V2 / "sha-manifest.json")):
        raise ValueError("case-local package manifest changed")
    for name, record in package["files"].items():
        path = HERE / name
        if (not path.is_file() or path.stat().st_size != record["bytes"]
                or sha(path) != record["sha256"]):
            raise ValueError("case-local file changed: " + name)
    request = read(HERE / "admission-request.json")
    if (request.get("go") is not False or request.get("stage_only") is not True
            or request.get("host") != "node0" or request.get("case_id") != "SOLR-15"
            or request.get("mode") != "healthy"
            or request.get("config_sha256") != sha(config_path)
            or request.get("runner_sha256") != sha(Path(__file__))
            or request.get("intended_output") != str(OUT)):
        raise ValueError("node0 admission request changed")
    return {"config_sha256": sha(config_path),
            "runner_sha256": sha(Path(__file__)),
            "manifest_sha256": sha(HERE / "sha-manifest.json"),
            "intended_output": str(OUT), **release}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    metadata = preflight()
    if args.preflight_only:
        print(json.dumps({"status": "preflight_passed", "mode": "healthy",
                          "host_intent": "node0", **metadata}, sort_keys=True))
        return 0
    if socket.gethostname().split(".", 1)[0] != "node0":
        parser.error("node0 runtime required")
    if args.admission_receipt is None:
        parser.error("node0 steward GO receipt required before starting a JVM")
    if args.admission_receipt.resolve() != HERE / "admission-healthy-node0.json":
        parser.error("case-local node0 GO receipt required")
    receipt = read(args.admission_receipt)
    required = {"go": True, "host": "node0", "case_id": "SOLR-15",
                "mode": "healthy", "config_sha256": metadata["config_sha256"],
                "runner_sha256": metadata["runner_sha256"],
                "intended_output": str(OUT)}
    if any(receipt.get(key) != value for key, value in required.items()):
        parser.error("node0 steward GO receipt missing or mismatched")
    if OUT.exists():
        raise ValueError("healthy-only output already exists")
    lock_root = Path("/tmp/mallory-lanes")
    lock_root.mkdir(parents=True, exist_ok=True)
    with ExitStack() as locks:
        for name in ("zookeeper-node0-source.lock", "solr-node0-v1.lock",
                     "solr-source-graphchecker-8.11.4.lock"):
            handle = locks.enter_context((lock_root / name).open("a+"))
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if OUT.exists():
            raise ValueError("healthy output appeared while acquiring locks")
        if shutil.disk_usage(ROOT).free < 7_650_410_496:
            raise ValueError("insufficient free disk for healthy trial")
        available_kib = next(int(row.split()[1]) for row in
                             Path('/proc/meminfo').read_text().splitlines()
                             if row.startswith('MemAvailable:'))
        if available_kib < 8_388_608:
            raise ValueError("insufficient available RAM for healthy trial")
        processes = subprocess.check_output(['ps', '-eo', 'user=,comm='], text=True)
        if any(row.split() == [getpass.getuser(), 'java']
               for row in processes.splitlines()):
            raise ValueError("another user JVM is running on node0")
        print(json.dumps({"status": "admitted", "go_receipt_sha256": sha(args.admission_receipt),
                          **metadata}, sort_keys=True), flush=True)
        state = campaign.run(HERE / "config-healthy-node0.json", OUT)
    print(json.dumps({"status": state["status"],
                      "completed_trials": state["completed_trials"]}, sort_keys=True))
    return subprocess.run([sys.executable, str(HERE / "audit_healthy.py"), str(OUT)],
                          check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
