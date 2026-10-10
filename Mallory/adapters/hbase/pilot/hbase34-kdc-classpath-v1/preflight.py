#!/usr/bin/env python3
"""Verify the isolated HBASE-34 MiniKdc classpath repair without starting Java."""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import struct
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")
DIST = Path("/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib")
CORE = ROOT / "Mallory/dispatch/releases/815cba9b-target-absent-v1"
OLD_ARCHIVE = ROOT / "data/mallory/evidence_archives/calibration/HBASE-34.tar.gz"
OID = "org/apache/directory/api/asn1/util/Oid.class"
I18N = "org/apache/directory/api/i18n/I18n.class"
FIELD = "ERR_00003_INVALID_OID"


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def sha(path: Path) -> str:
    require(path.is_file(), f"missing file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def member(jar: Path, name: str) -> bytes:
    with zipfile.ZipFile(jar) as archive:
        return archive.read(name)


def field_refs(bytecode: bytes) -> set[tuple[str, str]]:
    """Read class constant-pool Fieldrefs only; no JVM or class loading."""
    require(bytecode[:4] == b"\xca\xfe\xba\xbe", "invalid Java class")
    count = struct.unpack_from(">H", bytecode, 8)[0]
    entries: list[tuple | None] = [None] * count
    offset = 10
    index = 1
    while index < count:
        tag = bytecode[offset]
        offset += 1
        if tag == 1:
            length = struct.unpack_from(">H", bytecode, offset)[0]
            offset += 2
            entries[index] = (tag, bytecode[offset:offset + length].decode("utf-8"))
            offset += length
        elif tag in (3, 4):
            offset += 4
        elif tag in (5, 6):
            offset += 8
            index += 1
        elif tag in (7, 8, 16, 19, 20):
            entries[index] = (tag, struct.unpack_from(">H", bytecode, offset)[0])
            offset += 2
        elif tag in (9, 10, 11, 12, 17, 18):
            entries[index] = (tag, *struct.unpack_from(">HH", bytecode, offset))
            offset += 4
        elif tag == 15:
            offset += 3
        else:
            raise ValueError(f"unsupported class constant-pool tag {tag}")
        index += 1
    refs = set()
    for entry in entries:
        if entry is not None and entry[0] == 9:
            owner = entries[entries[entry[1]][1]][1]
            name = entries[entries[entry[2]][1]][1]
            refs.add((owner, name))
    return refs


def preflight(node1: bool) -> dict:
    pins = json.loads((HERE / "manifest.json").read_text())
    config = json.loads((HERE / "healthy.json").read_text())
    for relative, digest in pins["case_files"].items():
        require(sha(HERE / relative) == digest, f"package changed: {relative}")
    require(sha(ROOT / pins["source_receipt"]["path"]) ==
            pins["source_receipt"]["sha256"], "corrected source receipt changed")
    require(sha(OLD_ARCHIVE) == pins["old_archive_sha256"],
            "prior failure archive changed")
    with tarfile.open(OLD_ARCHIVE, "r:gz") as archive:
        stderr = archive.extractfile("trials/r0000/stderr.log").read()
    require(b"NoSuchFieldError: ERR_00003_INVALID_OID" in stderr and
            b"Oid.processStateStart" in stderr and
            b"MiniKdc.start" in stderr, "the recorded failure changed")
    source_commit = subprocess.check_output(
        ["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True).strip()
    require(source_commit == pins["source_commit"], "source commit changed")
    for relative, digest in pins["source_files"].items():
        require(sha(SOURCE / relative) == digest, f"source changed: {relative}")

    for path, digest in pins["jars"].items():
        require(sha(Path(path)) == digest, f"jar changed: {path}")
    all_m20 = DIST / "api-all-1.0.0-M20.jar"
    asn1_m20 = DIST / "api-asn1-api-1.0.0-M20.jar"
    asn1_217 = DIST / "api-asn1-api-2.1.7.jar"
    i18n_m20 = DIST / "api-i18n-1.0.0-M20.jar"
    i18n_217 = DIST / "api-i18n-2.1.7.jar"
    require(member(all_m20, OID) == member(asn1_m20, OID) and
            member(all_m20, I18N) == member(i18n_m20, I18N),
            "api-all does not contain the matching M20 ASN.1 and i18n classes")
    require(("org/apache/directory/api/i18n/I18n", FIELD) in
            field_refs(member(asn1_217, OID)) and
            ("org/apache/directory/api/i18n/I18n", FIELD) not in
            field_refs(member(all_m20, OID)) and
            FIELD.encode() not in member(all_m20, I18N) and
            FIELD.encode() in member(i18n_217, I18N),
            "the recorded mixed-version linkage explanation no longer holds")

    classpath = config["command"][config["command"].index("-cp") + 1].split(":")
    require(classpath[:4] == [
        str(ROOT / "Mallory/adapters/hbase/pilot/mallory-hbase-selected-junit-v3.jar"),
        str(ROOT / "Mallory/adapters/hbase/target/mallory-hbase-adapter.jar"),
        str(ROOT / "Mallory/adapters/hbase/overlays/hbase28-constructor-actor-v1/runtime/junit-platform-launcher.jar"),
        str(all_m20)], "M20 API jar must precede the HBase wildcard")
    require(str(DIST / "*") in classpath[4:], "HBase distribution wildcard missing")
    for first in classpath[:3]:
        with zipfile.ZipFile(first) as archive:
            require(OID not in archive.namelist() and I18N not in archive.namelist(),
                    "an earlier runtime jar shadows the M20 API jar")
    require(config["case_id"] == "HBASE-34" and
            config["cluster_test"] ==
            "org.apache.hadoop.hbase.security.token.TestGenerateDelegationToken#testOnlyToken" and
            config["command"][-2:] == [
                "org.apache.hadoop.hbase.security.token.TestGenerateDelegationToken",
                "testOnlyToken"] and
            config["cwd"] == str(SOURCE) and
            config["calibration_only"] is True and
            config["auto_promote_if_healthy"] is False,
            "original true-cluster healthy selector changed")
    require(config["budget"] == {"trials": 1, "seconds": 900,
            "max_faults_per_trial": 1, "trial_timeout_seconds": 600},
            "environment-repair-only budget changed")
    require(config["target"]["check_sites"] == [pins["target_check"]] and
            config["target"]["throw_site"] == pins["target_throw"],
            "exact target changed")
    require(config["expected_target_class_sha256"] == pins["target_class_sha256"],
            "target class pin changed")
    require(hashlib.sha256(member(DIST / "hbase-server-2.6.6.jar",
            "org/apache/hadoop/hbase/security/token/AuthenticationTokenSecretManager.class"
            )).hexdigest() == pins["target_class_sha256"],
            "compiled target class changed")
    require(hashlib.sha256(member(DIST / "hbase-server-2.6.6-tests.jar",
            "org/apache/hadoop/hbase/security/token/TestGenerateDelegationToken.class"
            )).hexdigest() == pins["test_class_sha256"],
            "compiled unchanged cluster JUnit changed")
    for record in config["runtime_artifacts"]:
        require(sha(Path(record["path"])) == record["sha256"],
                f"runtime artifact changed: {record['path']}")
    require(sha(CORE / "manifest.json") == pins["core_manifest_sha256"],
            "frozen campaign core changed")
    sys.path.insert(0, str(CORE))
    from Mallory.core.campaign import validate_config
    validate_config(config)
    if node1:
        require(socket.gethostname().split(".")[0] == "node1", "wrong host")
    return {"case_id": "HBASE-34", "kind": "KDC_classpath_repair_static_preflight",
            "status": "passed", "jvm_started": False,
            "explicit_first_directory_api": str(all_m20),
            "healthy_runtime_attested": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node1", action="store_true")
    args = parser.parse_args()
    print(json.dumps(preflight(args.node1), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
