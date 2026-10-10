#!/usr/bin/env python3
"""JVM-free HBASE-28 source and artifact check for healthy observation only."""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[5]
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")
DIST = Path("/users/ZhenyuLi/.baseline-deps/hbase-2.6.6")
OVERLAY = HERE.parent


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha(path: Path) -> str:
    require(path.is_file(), f"missing pinned file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(path: Path, expected: str) -> None:
    actual = sha(path)
    require(actual == expected, f"SHA mismatch for {path}: {actual}")


def properties(path: Path) -> dict[str, str]:
    root = ET.parse(path).getroot()
    return {p.findtext("name"): p.findtext("value")
            for p in root.findall("property") if p.findtext("name")}


def preflight(node1: bool) -> None:
    config = json.loads((HERE / "config.json").read_text())
    review = json.loads((HERE / "source-limitation.json").read_text())
    sites = json.loads((HERE / "sites.json").read_text())
    receipt = json.loads((HERE / "stage-receipt.json").read_text())
    require(receipt["case_id"] == "HBASE-28" and receipt["status"] == "staged_no_jvm",
            "wrong stage receipt")
    for file, key in (("config.json", "config_sha256"),
                      ("sites.json", "site_sha256"),
                      ("source-limitation.json", "source_limitation_sha256"),
                      ("preflight.py", "preflight_sha256")):
        check(HERE / file, receipt[key])
    require(config["case_id"] == "HBASE-28" and config["system"] == "hbase" and
            config["cluster_test"] == review["selected_junit"] and
            config["command"][-2:] == ["org.apache.hadoop.hbase.TestInfoServers",
                                       "testInfoServersRedirect"],
            "wrong selected JUnit")
    require(config["calibration_only"] is True and
            config["auto_promote_if_healthy"] is False and
            config["budget"] == {"trials": 1, "seconds": 900,
                                 "max_faults_per_trial": 1,
                                 "trial_timeout_seconds": 300} and
            config["require_event_time_paths"] is True and
            config["reject_coarse_roots"] is True and
            config["allow_local_timeline_doors"] is False,
            "healthy-only strict observation policy changed")
    require(config["agent_include"] == [
        "org.apache.hadoop.hbase.regionserver.HRegionServer",
        "org.apache.hadoop.hbase.util.Addressing",
        "org.apache.hadoop.hbase.util.JVMClusterUtil"] and
            config["agent_properties"]["auto.io.doors"] is False and
            config["agent_properties"]["adapter.transformers"].endswith(
                "edu.uva.liftlab.mallory.hbase.hbase28.ConstructorActorTransformer"),
            "typed door or actor hook changed")
    require(config["site_file"] == str(HERE / "sites.json") and
            {"path": config["site_file"], "sha256": receipt["site_sha256"]}
            in config["runtime_artifacts"], "site artifact changed")
    require(config["target"]["check_sites"] == [review["selected_guard"]["site"]] and
            config["target"]["throw_site"] == review["selected_guard"]["throw_site"],
            "selected target changed")
    require(sites["targets"][0]["line"] == 2482 and
            sites["targets"][1]["line"] == 2487 and
            sites["doors"] == [{
                "clazz": "org.apache.hadoop.hbase.util.Addressing",
                "method": "isLocalAddress",
                "descriptor": "(Ljava/net/InetAddress;)Z",
                "line": 148,
                "callee": "java.net.NetworkInterface#getByInetAddress"
                          "(Ljava/net/InetAddress;)Ljava/net/NetworkInterface;",
                "exception_class": "java.net.SocketException",
            }], "exact physical typed selector changed")
    for relative, digest in review["source_sha256"].items():
        check(SOURCE / relative, digest)
    paths = review["source_paths"]
    target = (SOURCE / paths["target"]).read_text()
    addressing = (SOURCE / paths["addressing"]).read_text()
    test = (SOURCE / paths["test"]).read_text()
    require('this.conf.get("hbase.regionserver.info.bindAddress", "0.0.0.0")' in target
            and 'this.conf.get("hbase.master.info.bindAddress", "0.0.0.0")' in target
            and "if (!Addressing.isLocalAddress(InetAddress.getByName(addr)))" in target,
            "selected configured guard changed")
    require("addr.isAnyLocalAddress() || addr.isLoopbackAddress()" in addressing and
            "if (!local)" in addressing and
            "NetworkInterface.getByInetAddress(addr) != null" in addressing and
            "catch (SocketException e)" in addressing,
            "local-address fast path or typed catch changed")
    require('UTIL.startMiniCluster();' in test and
            'new URL("http://localhost:" + port + "/index.html")' in test and
            "hbase.master.info.bindAddress" not in test and
            "hbase.regionserver.info.bindAddress" not in test,
            "mapped test or localhost dependency changed")
    keys = ("hbase.master.info.bindAddress", "hbase.regionserver.info.bindAddress")
    defaults = properties(SOURCE / paths["defaults"])
    require(all(defaults.get(key) == "0.0.0.0" for key in keys),
            "source default bind address changed")
    for path in (DIST / "conf").glob("*.xml"):
        local = properties(path)
        require(not any(key in local for key in keys),
                f"distribution configuration overrides bind address: {path}")
    prior = json.loads((REPO / "data/mallory/calibration/HBASE-28/result.json").read_text())
    require(prior["status"] == "healthy_node_identity_missing" and
            prior["target_node_named"] is False and
            prior["fault_trials_completed"] == 0,
            "prior named-target gap changed")
    for jar_name, classes in receipt["compiled_class_sha256"].items():
        jar_path = DIST / "lib" / jar_name
        check(jar_path, receipt["compiled_jar_sha256"][jar_name])
        with zipfile.ZipFile(jar_path) as jar:
            for class_name, digest in classes.items():
                require(hashlib.sha256(jar.read(class_name)).hexdigest() == digest,
                        f"compiled class changed: {class_name}")
    require(config["expected_target_class_sha256"] ==
            receipt["compiled_class_sha256"]["hbase-server-2.6.6.jar"][
                "org/apache/hadoop/hbase/regionserver/HRegionServer.class"],
            "target class pin changed")
    core = config["core_release"]
    manifest = Path(core["path"]) / "manifest.json"
    check(manifest, core["manifest_sha256"])
    for relative, digest in json.loads(manifest.read_text())["files"].items():
        check(manifest.parent / relative, digest)
    check(OVERLAY / "runtime/overlay.jar", receipt["actor_overlay_sha256"])
    check(Path(config["agent_jar"]), receipt["agent_sha256"])
    for artifact in config["runtime_artifacts"]:
        check(Path(artifact["path"]), artifact["sha256"])
    if node1:
        require(socket.gethostname().split(".")[0] == "node1", "wrong host")
        for relative, digest in review["source_sha256"].items():
            check(Path(config["source_equivalent_root"]) / relative, digest)
    print("PASS HBASE-28 JVM-free observation preflight: exact guard, default bind "
          "bypasses alternate typed door; indexed actor and source/class/site/core pins")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node1", action="store_true")
    parser.add_argument("--outcome", type=Path)
    args = parser.parse_args()
    try:
        preflight(args.node1)
    except (ValueError, FileNotFoundError, KeyError, zipfile.BadZipFile,
            ET.ParseError) as exc:
        if args.outcome:
            args.outcome.parent.mkdir(parents=True, exist_ok=True)
            args.outcome.write_text(json.dumps({"schema_version": 1, "case_id": "HBASE-28",
                "kind": "static_preflight_gap", "status": "source_or_path_gap",
                "reason": str(exc), "jvm_started": False}, indent=2) + "\n")
        raise SystemExit(f"HBASE-28 observation preflight gap: {exc}")


if __name__ == "__main__":
    main()
