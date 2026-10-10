#!/usr/bin/env python3
"""Static admission for the isolated HBASE-34 MiniKdc BC classpath repair."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import socket
import struct
import sys
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
PARENT = HERE.parent / "hbase34-kdc-classpath-v1"
ROOT = HERE.parents[4]
PROVIDER = "org/bouncycastle/jce/provider/BouncyCastleProvider.class"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha(path: Path) -> str:
    require(path.is_file(), f"missing: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def class_major(bytecode: bytes) -> int:
    require(bytecode[:4] == b"\xca\xfe\xba\xbe", "invalid Java class")
    return struct.unpack_from(">H", bytecode, 6)[0]


def classpath(config: dict) -> list[str]:
    command = config["command"]
    require(command.count("-cp") == 1, "expected one JVM classpath")
    return command[command.index("-cp") + 1].split(":")


def validate_v2_config(config: dict, parent: dict, pins: dict) -> None:
    """Allow only the isolated classpath, pin, and descriptive v2 changes."""
    expected = json.loads(json.dumps(parent))
    old_cp = classpath(expected)
    bc = pins["bc_order"]
    require(len(bc) == 3, "expected one BC 1.82 provider/util/pkix trio")
    require(set(bc) == set(pins["bc_jars"]), "BC order and pins differ")
    require([Path(p).name for p in bc] == [
        "bcprov-jdk18on-1.82.jar", "bcutil-jdk18on-1.82.jar",
        "bcpkix-jdk18on-1.82.jar"], "BC versions differ")
    require(old_cp[3].endswith("/api-all-1.0.0-M20.jar"),
            "parent M20 Directory API order changed")
    cp_index = expected["command"].index("-cp") + 1
    expected["command"][cp_index] = ":".join(old_cp[:4] + bc + old_cp[4:])
    expected["runtime_artifacts"] += [
        {"path": path, "sha256": pins["bc_jars"][path]}
        for path in bc]
    expected["revision"] = "HBASE-34-kdc-M20-BC1.82-classpath-v2-healthy"
    expected["mapping"]["classpath_repair"] = (
        "explicit M20 Directory API and pinned Bouncy Castle 1.82 trio "
        "before wildcard distribution jars; static admission only")
    expected["mapping"]["status"] = "pending_environment_repair_healthy_only_v2"
    require(config == expected, "v2 changed more than the allowed classpath repair")
    require(classpath(config)[4:7] == bc, "BC jars not immediately after M20 API")
    require(config["calibration_only"] is True and
            config["auto_promote_if_healthy"] is False and
            config["budget"]["trials"] == 1,
            "healthy-only admission changed")


def preflight(node1: bool = False) -> dict:
    pins = load_json(HERE / "manifest.json")
    require(pins["case_id"] == "HBASE-34" and pins["schema_version"] == 2,
            "wrong package manifest")
    for name, digest in pins["case_files"].items():
        require(sha(HERE / name) == digest, f"package changed: {name}")
    require(sha(PARENT / "manifest.json") == pins["parent_manifest_sha256"] and
            sha(PARENT / "healthy.json") == pins["parent_config_sha256"] and
            sha(PARENT / "sites.json") == pins["parent_sites_sha256"],
            "parent package changed")
    require((HERE / "sites.json").read_bytes() == (PARENT / "sites.json").read_bytes(),
            "target sites changed")
    parent_module_spec = importlib.util.spec_from_file_location(
        "hbase34_parent_preflight", PARENT / "preflight.py")
    require(parent_module_spec is not None and parent_module_spec.loader is not None,
            "cannot load parent preflight")
    parent_module = importlib.util.module_from_spec(parent_module_spec)
    parent_module_spec.loader.exec_module(parent_module)
    parent_result = parent_module.preflight(node1)
    require(parent_result["status"] == "passed" and
            parent_result["jvm_started"] is False,
            "parent package failed static admission")

    config = load_json(HERE / "healthy.json")
    parent = load_json(PARENT / "healthy.json")
    validate_v2_config(config, parent, pins)
    require(sha(Path(pins["hbase_source_pom"])) == pins["hbase_source_pom_sha256"],
            "HBase source POM changed")
    pom = Path(pins["hbase_source_pom"]).read_text()
    require("<artifactId>bcprov-jdk18on</artifactId>" in pom and
            "<artifactId>bcpkix-jdk18on</artifactId>" in pom,
            "HBase test BC dependency family changed")
    for path, digest in pins["bc_jars"].items():
        require(sha(Path(path)) == digest, f"BC jar changed: {path}")
    cp = classpath(config)
    # The Java application loader takes the first matching class. The explicit
    # BC provider must precede every wildcard and have no earlier duplicate.
    for item in cp[:4]:
        if item.endswith(".jar"):
            with zipfile.ZipFile(item) as archive:
                require(PROVIDER not in archive.namelist(),
                        f"BC provider shadowed by {item}")
    for member, path in pins["bc_classes"].items():
        with zipfile.ZipFile(path) as archive:
            major = class_major(archive.read(member))
        require(major <= pins["java_max_class_major"],
                f"{member} requires Java newer than selected Java 8")
    require(PROVIDER in pins["bc_classes"] and
            cp[4] == pins["bc_classes"][PROVIDER],
            "the missing provider is not in the first BC jar")

    sys.path.insert(0, str(Path(config["core_release"])))
    from Mallory.core.campaign import validate_config
    validate_config(config)
    if node1:
        require(socket.gethostname().split(".")[0] == "node1", "wrong host")
        failure = pins["v1_failure"]
        stderr = Path(failure["node1_stderr_path"])
        require(sha(stderr) == failure["sha256"], "v1 stderr changed")
        text = stderr.read_text(errors="replace")
        require(failure["signature"] in text and failure["frame"] in text and
                "MALLORY_JUNIT found=0 succeeded=0 failed=0" in text,
                "v1 missing-provider failure changed")
    return {"case_id": "HBASE-34", "status": "passed",
            "kind": "MiniKdc_BC1.82_classpath_static_admission",
            "parent_status": parent_result["status"], "jvm_started": False,
            "runtime_validated": False, "node1_v1_failure_verified": node1,
            "bc_jar_sha256": pins["bc_jars"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node1", action="store_true")
    args = parser.parse_args()
    print(json.dumps(preflight(args.node1), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
