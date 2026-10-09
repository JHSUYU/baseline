#!/usr/bin/env python3
"""Offline SHA and semantic checks for the HBASE-31 typed healthy pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import subprocess
from pathlib import Path
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")
STAGED = HERE.parent / "HBASE-31-37-typed-door-v1"
SERVER_JAR = Path("/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/hbase-server-2.6.6.jar")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def check(path: Path, expected: str) -> None:
    require(path.is_file() and sha(path) == expected, f"SHA mismatch: {path}")


def main(allow_detached_source: bool = False) -> None:
    admission = json.loads((HERE / "admission.json").read_text())
    config_path = STAGED / "HBASE-31.healthy.json"
    sites_path = STAGED / "HBASE-31.sites.json"
    check(config_path, admission["staged_config_sha256"])
    check(sites_path, admission["staged_sites_sha256"])
    config = json.loads(config_path.read_text())
    sites = json.loads(sites_path.read_text())
    normalized = json.dumps(config, sort_keys=True, indent=2) + "\n"
    require(hashlib.sha256(normalized.encode()).hexdigest() ==
            admission["campaign_config_sha256"], "campaign config serialization changed")

    commit = subprocess.run(["git", "-C", str(SOURCE), "rev-parse", "HEAD"],
                            text=True, capture_output=True)
    if commit.returncode == 0:
        require(commit.stdout.strip() == admission["source_commit"],
                "source commit changed")
    else:
        require(allow_detached_source and socket.gethostname().split(".")[0] == "node1" and
                (SOURCE / ".git").read_text().strip() ==
                "gitdir: /users/ZhenyuLi/hbase/.git/worktrees/hbase-2.6.6",
                "source Git metadata unavailable without explicit node1 detached mode")
    for relative, key in ((config["target"]["source_path"], "target_source_sha256"),
                          ("hbase-server/src/test/java/org/apache/hadoop/hbase/regionserver/"
                           "TestRegionMove.java", "test_source_sha256"),
                          ("hbase-server/src/main/java/org/apache/hadoop/hbase/master/procedure/"
                           "RSProcedureDispatcher.java", "dispatcher_source_sha256")):
        check(SOURCE / relative, config["mapping"][key])

    check(SERVER_JAR, admission["compiled_server_jar_sha256"])
    with ZipFile(SERVER_JAR) as jar:
        for member, key in (
            ("org/apache/hadoop/hbase/regionserver/RSRpcServices.class",
             "compiled_target_class_sha256"),
            ("org/apache/hadoop/hbase/master/procedure/"
             "RSProcedureDispatcher$ExecuteProceduresRemoteCall.class",
             "compiled_dispatcher_class_sha256"),
        ):
            require(hashlib.sha256(jar.read(member)).hexdigest() == admission[key],
                    f"compiled class changed: {member}")
    require(config["expected_target_class_sha256"] ==
            admission["compiled_target_class_sha256"], "target class pin changed")

    release = REPO / "Mallory/dispatch/releases" / admission["core_release_id"]
    manifest = release / "manifest.json"
    check(manifest, admission["core_manifest_sha256"])
    core = json.loads(manifest.read_text())
    require(core["release_id"] == admission["core_release_id"], "core identity changed")
    for relative, expected in core["files"].items():
        check(release / relative, expected)
    require(config["core_release"]["release_id"] == core["release_id"] and
            config["core_release"]["manifest_sha256"] == sha(manifest),
            "config core release changed")

    for artifact in config["runtime_artifacts"]:
        check(Path(artifact["path"]), artifact["sha256"])
    adapter = Path(config["agent_properties"]["adapter.jar"])
    check(adapter, admission["adapter_jar_sha256"])
    require(adapter in [Path(part) for part in config["command"][6].split(":")],
            "adapter absent from test classpath")
    require(config["agent_jar"] in [row["path"] for row in config["runtime_artifacts"]],
            "agent absent from artifact pins")

    require(config["case_id"] == admission["case_id"] and
            config["cluster_test"] == admission["exact_test"] and
            config["command"][-3:] == ["edu.uva.liftlab.mallory.hbase.pilot.SelectedJUnit",
                                       "org.apache.hadoop.hbase.regionserver.TestRegionMove",
                                       "testDisableAndMove"], "selected JUnit changed")
    require(config["calibration_only"] is True and
            config["auto_promote_if_healthy"] is False and
            config["mapping"]["fault_admission_blocked"] is True and
            config["require_event_time_paths"] is True and
            config["reject_coarse_roots"] is True and
            config["allow_local_timeline_doors"] is False and
            config["agent_properties"]["auto.io.doors"] is False and
            config["budget"]["trials"] == 1, "healthy-only gate changed")
    require(config["site_file"] == str(sites_path) and len(sites["doors"]) == 1,
            "typed catalog changed")
    door = sites["doors"][0]
    actual_door = (f'{door["clazz"]}#{door["method"]}{door["descriptor"]}'
                   f'@{door["line"]}:door:1')
    require(actual_door == admission["typed_door"] and
            door["callee"].endswith("#executeProcedures(Lorg/apache/hbase/thirdparty/"
                                    "com/google/protobuf/RpcController;Lorg/apache/hadoop/"
                                    "hbase/shaded/protobuf/generated/AdminProtos$"
                                    "ExecuteProceduresRequest;)Lorg/apache/hadoop/hbase/"
                                    "shaded/protobuf/generated/AdminProtos$"
                                    "ExecuteProceduresResponse;") and
            door["exception_class"] == "java.io.IOException", "typed RPC changed")
    require(config["target"]["check_sites"] == [admission["target_check"]] and
            config["target"]["throw_site"] == admission["target_throw"],
            "exact guard changed")
    provenance = "detached-source content match" if commit.returncode else "source commit match"
    print("PASS HBASE-31 offline preflight: pinned source, classes, core, adapter, "
          f"and typed healthy gate ({provenance})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-detached-source", action="store_true")
    main(parser.parse_args().allow_detached_source)
