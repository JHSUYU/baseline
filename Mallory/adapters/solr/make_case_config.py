#!/usr/bin/env python3
"""Materialize a direct JUnit Mallory config for an inventory Solr case."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

from run_pilot import HERE, MALLORY, selected_test


CALL = re.compile(r"// (?:InterfaceMethod|Method) ([\w/$]+)\.([\w$]+):(\S+)")
ZK_OPS = frozenset({"exists", "getChildren", "getData", "setData", "create",
                    "delete", "makePath", "multi", "getACL", "setACL"})


def prepare_sites(case_id: str, base: dict) -> Path:
    """Add only direct, compiled ZK I/O calls with a declared exception type.

    The output remains scoped to the target class. Its exact call descriptors
    come from the Solr 8.11.4 distribution bytecode used by the JUnit runner.
    """
    generated = MALLORY / "cases" / (case_id + ".sites.json")
    sites = json.loads(generated.read_text())
    if case_id == "SOLR-05":
        # Keep the direct waitForState door within the exact register method.
        sites.setdefault("doors", []).append({
            "class": "org.apache.solr.cloud.ZkController", "method": "register",
            "callee": ("org.apache.solr.common.cloud.ZkStateReader#waitForState"
                       "(Ljava/lang/String;JLjava/util/concurrent/TimeUnit;"
                       "Ljava/util/function/Predicate;)V"),
            "exception_class": "java.util.concurrent.TimeoutException"})
    target_owner = base["target"]["throw_site"].split("#", 1)[0]
    owners = {target_owner, "org.apache.solr.cloud.ZkController"}
    dist = Path.home() / ".baseline-deps/solr-8.11.4/dist"
    additions = []
    for owner in sorted(owners):
        jar = dist / ("solr-solrj-8.11.4.jar" if ".solrj." in owner
                      or owner.startswith("org.apache.solr.common.")
                      else "solr-core-8.11.4.jar")
        javap = subprocess.run(["javap", "-classpath", str(jar), "-c", "-p", owner],
                               text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               check=True).stdout
        for match in CALL.finditer(javap):
            callee_owner, name, descriptor = match.groups()
            exception = None
            if callee_owner == "org/apache/solr/common/cloud/SolrZkClient" and name in ZK_OPS:
                exception = "org.apache.zookeeper.KeeperException$ConnectionLossException"
            elif callee_owner == "org/apache/solr/common/cloud/ZkStateReader":
                if name == "waitForState":
                    exception = "java.util.concurrent.TimeoutException"
                elif name == "forceUpdateCollection":
                    exception = "org.apache.zookeeper.KeeperException$ConnectionLossException"
            if exception is None:
                continue
            callee = callee_owner.replace("/", ".") + "#" + name + descriptor
            rule = {"class": owner, "callee": callee, "exception_class": exception}
            if rule not in additions:
                additions.append(rule)
    # A class can contain many ZK callsites; only the listed concrete APIs are
    # included, and cap the resulting rule set to guard accidental expansion.
    if len(additions) > 64:
        raise ValueError(f"too many bounded ZK rules for {case_id}: {len(additions)}")
    existing = sites.setdefault("doors", [])
    existing_keys = {(rule.get("class", rule.get("clazz")), rule.get("callee"),
                      rule.get("exception_class")) for rule in existing}
    existing.extend(rule for rule in additions
                    if (rule["class"], rule["callee"], rule["exception_class"])
                    not in existing_keys)
    output = HERE / "cases" / case_id / "sites.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(sites, indent=2, sort_keys=True) + "\n")
    return output


def make(case_id: str, *, trials: int = 80, seconds: int = 7200,
         max_faults: int = 10, source_root: Path | None = None,
         adapter_jar: Path | None = None, runner: Path | None = None,
         calibration_only: bool = False) -> dict:
    test_class, method, _, _ = selected_test(case_id)
    base = json.loads((MALLORY / "cases" / (case_id + ".json")).read_text())
    site = prepare_sites(case_id, base)
    inventory = json.loads((MALLORY / "cases" / "inventory.json").read_text())
    row = next(item for item in inventory["cases"] if item["case_id"] == case_id)
    if not row.get("eligibility", {}).get("may_dispatch_healthy_seed", True):
        base["calibration_only"] = True
        base["auto_promote_if_healthy"] = False
        base.setdefault("mapping", {})["status"] = row["eligibility"]["state"]
    else:
        base.pop("calibration_only", None)
        base["auto_promote_if_healthy"] = True
    base["cluster_test"] = test_class + "#" + method
    selected_root = source_root or (Path.home() / ".mallory-worktrees/solr")
    if not selected_root.is_absolute():
        raise ValueError("Solr source root must be absolute")
    base["cwd"] = str(selected_root)
    base["source_equivalent_root"] = str(selected_root)
    selected_runner = runner or (HERE / "releases/v4/run_pilot.py")
    base["command"] = ["python3", str(selected_runner), case_id]
    if source_root is not None:
        base["command"].extend(["--source", str(selected_root)])
    base["command"].extend(["--output", "{trial_dir}", "--campaign", "--timeout", "420"])
    if calibration_only:
        base["calibration_only"] = True
        base["auto_promote_if_healthy"] = False
    base["agent_transport"] = "java_tool_options"
    versioned_agent = MALLORY / "instrumentation/target/mallory-agent-taskobserve-ordinal.jar"
    if versioned_agent.is_file():
        base["agent_jar"] = str(versioned_agent)
    base["site_file"] = str(site)
    target_owner = base["target"]["throw_site"].split("#", 1)[0]
    base["agent_include"] = sorted({target_owner,
                                    "org.apache.solr.cloud.ZkController",
                                    "org.apache.solr.client.solrj.impl.BaseHttpClusterStateProvider"})
    adapter_jar = adapter_jar or (HERE / "target/mallory-solr-adapter-v4.jar")
    if not adapter_jar.is_file():
        raise FileNotFoundError("build and pin the shaded Solr adapter jar: " + str(adapter_jar))
    base["agent_properties"] = {
        "adapter.jar": str(adapter_jar),
        "adapter.transformer": "edu.uva.liftlab.mallory.solr.SolrTransformer",
        "auto.io.doors": True,
        "coverage.methods": True,
        "coverage.branches": True,
        "state.fields": False,
        "state.maps": False,
    }
    base["budget"] = {"trials": trials, "seconds": seconds,
                      "max_faults_per_trial": max_faults,
                      "trial_timeout_seconds": 480}
    base["fault_types"] = ["EXCEPTION"]
    base["explore_outside_closure"] = True
    base.setdefault("env", {}).update({
        "MALLORY_SOLR_AGENT_JAR": str(Path(base["agent_jar"])),
        "MALLORY_SOLR_ADAPTER_JAR": str(adapter_jar),
    })
    artifact_paths = [Path(base["agent_jar"]),
                      Path(base["agent_properties"]["adapter.jar"]), site,
                      selected_runner, HERE / "solr_junit_runner.py"]
    base["runtime_artifacts"] = [
        {"path": str(path.resolve()),
         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in artifact_paths]
    # Bind only a role verified by an actual healthy run. Other sites stay
    # unbound until their own calibration produces the role to use.
    if case_id == "SOLR-05":
        base["target"]["node"] = "node1"
    compiled_hash = base.get("mapping", {}).get("compiled_class_sha256")
    if compiled_hash:
        base["expected_target_class_sha256"] = compiled_hash
    return base


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_id")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trials", type=int, default=80)
    parser.add_argument("--seconds", type=int, default=7200)
    parser.add_argument("--max-faults", type=int, default=10)
    parser.add_argument("--source-root", type=Path,
                        help="absolute isolated source root, also passed to the JUnit runner")
    parser.add_argument("--adapter-jar", type=Path,
                        help="immutable adapter artifact to pin")
    parser.add_argument("--runner", type=Path,
                        help="immutable direct JUnit runner wrapper to pin")
    parser.add_argument("--calibration-only", action="store_true")
    args = parser.parse_args()
    config = make(args.case_id, trials=args.trials, seconds=args.seconds,
                  max_faults=args.max_faults, source_root=args.source_root,
                  adapter_jar=args.adapter_jar, runner=args.runner,
                  calibration_only=args.calibration_only)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    print(args.output)
