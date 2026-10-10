#!/usr/bin/env python3
"""Static, no-JVM host-aware admission for immutable HBASE-32 v1 inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import subprocess
import sys
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent / "target-discovery-v1"
ROOT = HERE.parents[5]
CORE = ROOT / "Mallory/dispatch/releases/815cba9b-target-absent-v1"
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")
PRIOR = HERE / "prior-negative-result.json"
EXPECTED_COMMIT = "d5f63f523c065f963992ea4e74db268d17816631"
DOOR = ("org.apache.hadoop.hbase.client.FlushRegionCallable#call"
        "(Lorg/apache/hadoop/hbase/ipc/HBaseRpcController;)"
        "Lorg/apache/hadoop/hbase/shaded/protobuf/generated/"
        "AdminProtos$FlushRegionResponse;@81:door:1")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verify_zip_member(jar: Path, member: str, digest: str) -> None:
    with zipfile.ZipFile(jar) as archive:
        actual = hashlib.sha256(archive.read(member)).hexdigest()
    require(actual == digest, f"class changed: {jar}!{member}")


def source_snapshot(root: Path) -> tuple[str, int]:
    """Hash every source snapshot file, including its relative name and mode.

    This includes all files in the pinned HBase checkout except the .git
    worktree pointer. It does not depend on the host's Git object database.
    """
    digest = hashlib.sha256()
    count = 0
    for path in sorted(root.rglob("*")):
        if path == root / ".git":
            continue
        require(not path.is_symlink(), f"source snapshot symlink: {path}")
        if path.is_dir():
            continue
        require(path.is_file(), f"non-file in source snapshot: {path}")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        mode = b"100755" if path.stat().st_mode & stat.S_IXUSR else b"100644"
        contents = hashlib.sha256(path.read_bytes()).digest()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(mode)
        digest.update(contents)
        count += 1
    return digest.hexdigest(), count


def verify_source_identity(root: Path, manifest: dict,
                           pin: dict | None = None) -> dict:
    """Verify the entire source snapshot and Git provenance when available."""
    if pin is None:
        pin_path = HERE / "source-snapshot-pin.json"
        require(sha(pin_path) ==
                "61319bc699f2dd7832a8c21fe6f9c913f7387d86cd04bab13a895a41daf1ce57",
                "source snapshot pin changed")
        pin = load(pin_path)
    require(pin["algorithm"] == "sha256-path-mode-content-v1",
            "unknown source snapshot algorithm")
    require(sha(root / ".git") == pin["git_pointer_sha256"],
            "source Git worktree pointer changed")
    actual, count = source_snapshot(root)
    require(count == pin["file_count"] and actual == pin["sha256"],
            "HBase source snapshot changed")
    pointer = (root / ".git").read_text(encoding="utf-8").strip()
    require(pointer.startswith("gitdir: /"), "unexpected Git worktree pointer")
    metadata = Path(pointer.removeprefix("gitdir: "))
    if metadata.exists():
        commit = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
        tree = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD^{tree}"],
            text=True).strip()
        require(commit == manifest["source_commit"] and tree == pin["git_tree"],
                "HBase source Git revision changed")
        method = "git-and-full-snapshot"
    else:
        # Node1 has a copied, byte-identical source checkout, but not its
        # original host's Git worktree metadata. The complete snapshot and
        # its pointer were pinned against the clean source commit on node0.
        method = "full-snapshot-missing-worktree-metadata"
    return {"source_commit": manifest["source_commit"],
            "source_identity_method": method,
            "source_snapshot_sha256": actual,
            "source_snapshot_file_count": count}


def preflight(mode: str) -> dict:
    manifest_path = PACKAGE / "sha-manifest.json"
    manifest = load(manifest_path)
    require(sha(manifest_path) ==
            "bf21b73c5ac9eea9dfea46c32570d6492691dfa6bd4df1686adfa8e8144e7151",
            "immutable v1 package manifest changed")
    require(manifest["case_id"] == "HBASE-32", "wrong case manifest")
    require(manifest["source_commit"] == EXPECTED_COMMIT, "source revision changed")
    require(manifest["bootstrap_door"] == DOOR, "bootstrap door changed")
    for name, digest in manifest["case_files"].items():
        require(sha(PACKAGE / name) == digest, f"case file changed: {name}")

    source_identity = verify_source_identity(SOURCE, manifest)
    for name, digest in manifest["source_files"].items():
        require(sha(SOURCE / name) == digest, f"source changed: {name}")

    core_manifest = CORE / "manifest.json"
    require(sha(core_manifest) == manifest["core_manifest_sha256"],
            "frozen target-absent core changed")
    for name, digest in load(core_manifest)["files"].items():
        require(sha(CORE / name) == digest, f"frozen core changed: {name}")
    sys.path.insert(0, str(CORE))
    from Mallory.core.campaign import validate_config

    config = load(PACKAGE / f"config-{mode}.json")
    validate_config(config)
    require(config["calibration_only"] == (mode == "healthy"),
            "calibration mode changed")
    require(config["auto_promote_if_healthy"] == (mode == "full"),
            "promotion mode changed")
    require(config["core_release"] == str(CORE), "campaign core path changed")
    require(config["cwd"] == str(SOURCE), "source root changed")
    require(config["site_file"] == str(PACKAGE / "sites.json"), "site file changed")
    require(config["target_absent_bootstrap"]["door_sites"] == [DOOR],
            "exact bootstrap door changed")
    require(config["agent_properties"]["auto.io.doors"] is False,
            "explicit door numbering changed")
    require(config["expected_target_class_sha256"] ==
            manifest["target_class_sha256"], "target class pin changed")
    require(config["cluster_test"] ==
            "org.apache.hadoop.hbase.regionserver.TestRegionReplicaFailover#testSecondaryRegionKill",
            "unchanged cluster JUnit changed")
    require(config["budget"] == {
        "trials": 80, "seconds": 3600, "max_faults_per_trial": 3,
        "trial_timeout_seconds": 480}, "discovery budget changed")
    require(config["target"]["check_sites"] == [manifest["target_check"]],
            "target check changed")
    require(config["target"]["throw_site"] == manifest["target_throw"],
            "target throw changed")
    require(config["agent_properties"]["adapter.transformer"].split(",") == [
        "edu.uva.liftlab.mallory.hbase.HBaseAdapterTransformer",
        "edu.uva.liftlab.mallory.hbase32.HBase32ActorTransformer"],
        "actor overlay missing")
    for item in config["runtime_artifacts"]:
        require(sha(Path(item["path"])) == item["sha256"],
                f"runtime artifact changed: {item['path']}")

    sites = load(PACKAGE / "sites.json")
    require(len(sites["doors"]) == 1 and
            sites["doors"][0]["clazz"] == "org.apache.hadoop.hbase.client.FlushRegionCallable" and
            sites["doors"][0]["method"] == "call" and
            sites["doors"][0]["line"] == 81 and
            sites["doors"][0]["callee"] == manifest["rpc_callee"] and
            sites["doors"][0]["exception_class"] ==
            "org.apache.hadoop.hbase.DoNotRetryIOException",
            "the exact flushRegion exception door changed")
    require(any(row["line"] == 130 for row in sites["targets"]) and
            any(row["line"] == 136 for row in sites["targets"]),
            "target check/throw rules missing")

    for label, item in manifest["compiled"].items():
        jar = Path(item["jar"])
        require(sha(jar) == item["jar_sha256"], f"{label} jar changed")
        verify_zip_member(jar, item["member"], item["class_sha256"])
    # The class hash pins the bytecode reviewed with javap. These extra checks
    # reject an accidental pin to an unrelated class without invoking a JVM.
    with zipfile.ZipFile(manifest["compiled"]["flush_callable"]["jar"]) as archive:
        bytecode = archive.read(manifest["compiled"]["flush_callable"]["member"])
    for name in (b"flushRegion", b"BlockingInterface", b"LineNumberTable"):
        require(name in bytecode, "pinned flush RPC class is not recognizable")

    require(sha(PRIOR) == manifest["prior_negative_sha256"],
            "prior healthy negative receipt changed")
    old = load(PRIOR)
    require(old["healthy_junit_validation"]["status"] == "passed" and
            old["fault_trials_completed"] == 0 and
            old["cluster_test"] == config["cluster_test"] and
            old["target_reached_trials"] == 0 and
            old["healthy_seed_valid"] is False,
            "prior healthy negative receipt no longer matches")
    return {"case_id": "HBASE-32", "mode": mode,
            "static_preflight": "passed", "healthy_runtime_attested": False,
            **source_identity, "bootstrap_door": DOOR,
            "prior_healthy_exact_check_count": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("healthy", "full", "both"), default="both")
    args = parser.parse_args()
    modes = ("healthy", "full") if args.mode == "both" else (args.mode,)
    for mode in modes:
        print(json.dumps(preflight(mode), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
