#!/usr/bin/env python3
"""Verify HDFS-33/34 source audit pins and selected anchors without Java."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile


HERE = Path(__file__).resolve().parent
BASE = HERE.parents[4]
SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2")
RECEIPT = HERE / "source-receipt.json"


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_line(relative, number, fragment):
    path = SOURCE / relative
    lines = path.read_text().splitlines()
    if len(lines) < number or fragment not in lines[number - 1]:
        raise RuntimeError(f"source anchor changed: {path}:{number}")


def source_digest(reference):
    digest = hashlib.sha256()
    for relative in reference["paths"]:
        path = SOURCE / relative
        if path.is_symlink():
            payload = b"L" + os.fsencode(os.readlink(path))
        elif path.is_file():
            payload = b"F" + bytes.fromhex(sha(path))
        else:
            raise RuntimeError(f"source path missing: {path}")
        digest.update(os.fsencode(relative) + b"\0" + payload + b"\0")
    return digest.hexdigest()


def main():
    receipt = json.loads(RECEIPT.read_text())
    if receipt["schema_version"] != 1 or receipt["scope"] != "HDFS-33/34-original102-source-audit-v3":
        raise RuntimeError("receipt identity changed")
    if receipt["fault_or_full_admitted"] or receipt["jvm_launched"]:
        raise RuntimeError("audit admission state changed")
    for artifact in receipt["artifacts"]:
        path = Path(artifact["path"])
        if not path.is_file() or sha(path) != artifact["sha256"]:
            raise RuntimeError(f"missing or changed SHA-pinned artifact: {path}")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=SOURCE,
                          capture_output=True, text=True, check=True).stdout.strip()
    if head != receipt["source_commit"]:
        raise RuntimeError(f"source commit changed: {head}")
    reference = json.loads((BASE / "Mallory/dispatch/source_reference.json").read_text())
    frozen = reference["roots"]["/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3"]
    if (frozen["commit"] != receipt["source_commit"] or
            frozen["digest"] != receipt["source_digest"] or
            source_digest(frozen) != receipt["source_digest"]):
        raise RuntimeError("full source digest changed")

    hdfs = "hadoop-hdfs-project/hadoop-hdfs/"
    for relative, number, fragment in (
        (hdfs + "src/main/java/org/apache/hadoop/hdfs/server/datanode/DataStorage.java", 259, "assert bpStorage != null"),
        (hdfs + "src/main/java/org/apache/hadoop/hdfs/server/datanode/DataStorage.java", 338, "location.makeBlockPoolDir"),
        (hdfs + "src/main/java/org/apache/hadoop/hdfs/server/datanode/DataStorage.java", 340, "getBlockPoolSliceStorage(nsInfo)"),
        (hdfs + "src/main/java/org/apache/hadoop/hdfs/server/datanode/StorageLocation.java", 276, "DiskChecker.checkDir"),
        (hdfs + "src/main/java/org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage.java", 161, "case NON_EXISTENT"),
        (hdfs + "src/main/java/org/apache/hadoop/hdfs/server/datanode/fsdataset/impl/FsDatasetImpl.java", 545, "builder.build()"),
        (hdfs + "src/test/java/org/apache/hadoop/hdfs/server/datanode/TestDataNodeHotSwapVolumes.java", 403, "testAddOneNewVolume"),
        (hdfs + "src/main/java/org/apache/hadoop/hdfs/server/datanode/DataStorage.java", 739, "if (!federationSupported"),
        (hdfs + "src/main/java/org/apache/hadoop/hdfs/server/datanode/DataStorage.java", 740, "getNamespaceID() != nsInfo.getNamespaceID()"),
        (hdfs + "src/main/java/org/apache/hadoop/hdfs/server/datanode/BPServiceActor.java", 260, "bpNamenode.versionRequest()"),
        (hdfs + "src/main/java/org/apache/hadoop/hdfs/server/datanode/BPServiceActor.java", 265, "catch(IOException e"),
        (hdfs + "src/main/java/org/apache/hadoop/hdfs/server/datanode/BPOfferService.java", 394, "dn.initBlockPool(this)"),
        (hdfs + "src/main/java/org/apache/hadoop/hdfs/server/datanode/DataNode.java", 2259, "storage.recoverTransitionRead"),
        (hdfs + "src/main/java/org/apache/hadoop/hdfs/server/common/StorageInfo.java", 272, "props.load(in)"),
        (hdfs + "src/test/java/org/apache/hadoop/hdfs/TestDFSUpgradeFromImage.java", 296, "testUpgradeFromRel22Image"),
    ):
        require_line(relative, number, fragment)

    fixture = Path(receipt["fixture_archive"])
    versions = []
    with tarfile.open(fixture, "r:gz") as archive:
        for member in archive.getmembers():
            if member.name.endswith("/current/VERSION"):
                props = {}
                for line in archive.extractfile(member).read().decode().splitlines():
                    if "=" in line and not line.startswith("#"):
                        key, value = line.split("=", 1)
                        props[key] = value
                versions.append((member.name, props.get("namespaceID"), props.get("layoutVersion")))
    if (len(versions) != 10 or
            any(namespace != "-386152743" or layout != "-33"
                for _, namespace, layout in versions)):
        raise RuntimeError("0.22 VERSION fixture changed")

    staged = BASE / "Mallory/adapters/hdfs/cases/hdfs33-34-fresh-healthy-v2"
    for case in ("HDFS-33", "HDFS-34"):
        config = json.loads((staged / f"{case}-node2-healthy-v2.json").read_text())
        expected = receipt["cases"][case]
        if (config["cluster_test"] != expected["cluster_test"] or
                config["target"]["check_sites"] != expected["check_sites"] or
                config["target"]["throw_site"] != expected["throw_site"]):
            raise RuntimeError(f"{case} exact selector changed")

    old33 = json.loads(Path(receipt["archived_33_result"]).read_text())
    old34 = json.loads(Path(receipt["archived_34_result"]).read_text())
    stdout33 = Path(receipt["archived_33_stdout"]).read_text()
    stdout34 = Path(receipt["archived_34_stdout"]).read_text()
    cfg33 = json.loads(Path(receipt["archived_33_config"]).read_text())
    cfg34 = json.loads(Path(receipt["archived_34_config"]).read_text())
    if (cfg33["cluster_test"] != receipt["cases"]["HDFS-33"]["cluster_test"] or
            "Tests run: 1, Failures: 0, Errors: 0, Skipped: 0" not in stdout33 or
            not old33["feedback"]["target_reached"] or old33["feedback"]["target_threw"] or
            len(old33["feedback"]["target_instances"]) != 1 or
            old33["feedback"]["target_instances"][0]["node"] != "unknown" or
            cfg34["cluster_test"] != "org.apache.hadoop.hdfs.TestDFSStartupVersions#testVersions" or
            "Tests run: 1, Failures: 0, Errors: 0, Skipped: 0" not in stdout34 or
            not old34["feedback"]["target_threw"]):
        raise RuntimeError("archived target evidence changed")

    print(json.dumps({"status": "source_audit_pass", "cases": ["HDFS-33", "HDFS-34"],
                      "source_digest": receipt["source_digest"],
                      "fixture_version_entries": len(versions),
                      "jvm_launched": False, "fault_or_full_admitted": False}, sort_keys=True))


if __name__ == "__main__":
    main()
