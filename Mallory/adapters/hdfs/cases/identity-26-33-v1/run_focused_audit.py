"""Audit patched adapter against real Hadoop 3.4.3 bytes; no cluster startup."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[4]
BUILD = ROOT / "data/mallory/adapter-builds/identity-26-33-v1"
ADAPTER = BUILD / "Mallory/adapters/hdfs"
HDFS = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs")
DIST = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3")
M2 = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
AGENT = BUILD / "Mallory/instrumentation/target/mallory-agent.jar"


def artifact(path: Path) -> dict:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        raise RuntimeError(f"{argv[0]} failed ({result.returncode}):\n{result.stdout}")
    return result


def main() -> None:
    preflight = json.loads((OUT / "preflight.json").read_text())
    for rel, pinned in preflight["pristine_adapter"].items():
        assert artifact(Path(pinned["path"]))["sha256"] == pinned["sha256"], rel
    agent_sha = "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9"
    assert artifact(AGENT)["sha256"] == agent_sha
    jars = [M2 / f"asm-{name}/9.6/asm-{name}-9.6.jar"
            for name in ("tree", "util", "analysis")]
    jars.insert(0, M2 / "asm/9.6/asm-9.6.jar")
    assert all(path.exists() for path in jars)
    classpath = ":".join(str(p) for p in [ADAPTER / "target/classes", AGENT, *jars])
    dest = OUT / "build-tests"
    dest.mkdir(exist_ok=True)
    compiled = run(["javac", "-cp", classpath, "-d", str(dest),
                    str(OUT / "FocusedTransformerAudit.java")])
    production_jar = ADAPTER / "target/mallory-hdfs-adapter.jar"
    production_classpath = ":".join(str(p) for p in [production_jar, AGENT, *jars, dest])
    audited = run(["java", "-cp", production_classpath,
                   "FocusedTransformerAudit", str(HDFS), str(DIST)])
    lines = [line for line in audited.stdout.splitlines() if line.startswith("PASS ")]
    assert len(lines) == 7, audited.stdout
    paths = {
        "MiniDFSCluster": HDFS / "hadoop-hdfs-project/hadoop-hdfs/target/test-classes/org/apache/hadoop/hdfs/MiniDFSCluster.class",
        "MiniDFSCluster$Builder": HDFS / "hadoop-hdfs-project/hadoop-hdfs/target/test-classes/org/apache/hadoop/hdfs/MiniDFSCluster$Builder.class",
        "DataNode": HDFS / "hadoop-hdfs-project/hadoop-hdfs/target/classes/org/apache/hadoop/hdfs/server/datanode/DataNode.class",
        "DataStorage": HDFS / "hadoop-hdfs-project/hadoop-hdfs/target/classes/org/apache/hadoop/hdfs/server/datanode/DataStorage.class",
        "BlockPoolSliceStorage": HDFS / "hadoop-hdfs-project/hadoop-hdfs/target/classes/org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage.class",
        "DataStorage$VolumeBuilder": HDFS / "hadoop-hdfs-project/hadoop-hdfs/target/classes/org/apache/hadoop/hdfs/server/datanode/DataStorage$VolumeBuilder.class",
        "BPServiceActor": HDFS / "hadoop-hdfs-project/hadoop-hdfs/target/classes/org/apache/hadoop/hdfs/server/datanode/BPServiceActor.class",
    }
    receipt = {
        "schema_version": 1,
        "status": "adapter_built_and_real_class_bytecode_audited_no_minicluster_run",
        "no_minicluster_or_fault_trial_launched": True,
        "adapter_jar": artifact(production_jar),
        "agent_jar": artifact(AGENT),
        "isolated_source": {
            name: artifact(ADAPTER / "src/main/java/edu/uva/liftlab/mallory/adapters/hdfs" / name)
            for name in ("HdfsHooks.java", "HdfsMiniClusterTransformer.java")
        },
        "hadoop_class_bytes": {name: artifact(path) for name, path in paths.items()},
        "audit_source": artifact(OUT / "FocusedTransformerAudit.java"),
        "audit_class": artifact(dest / "FocusedTransformerAudit.class"),
        "compiler_output": compiled.stdout,
        "audit_output": audited.stdout,
        "passed_checks": lines,
    }
    audit_path = OUT / "audit-receipt.json"
    audit_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    sys.path.insert(0, str(ROOT))
    from Mallory.core.campaign import validate_config

    configurations = {}
    for case, target_class in (("HDFS-26", "BlockPoolSliceStorage"),
                               ("HDFS-33", "DataStorage$VolumeBuilder")):
        template = OUT / f"{case}-healthy-only.template.json"
        text = template.read_text().replace("__ISOLATED_HDFS_SOURCE_ROOT__", str(HDFS))
        text = text.replace("__ISOLATED_ADAPTER_JAR__", receipt["adapter_jar"]["path"])
        text = text.replace("__ADAPTER_SHA256__", receipt["adapter_jar"]["sha256"])
        config = json.loads(text)
        assert config["expected_target_class_sha256"] == receipt["hadoop_class_bytes"][target_class]["sha256"]
        config["budget"]["max_faults_per_trial"] = 1  # positive schema value; calibration has no fault trial
        config["mapping"]["status"] = "built_bytecode_audited_pending_healthy_admission"
        config["mapping"]["identity_overlay_audit_receipt"] = str(audit_path)
        config["mapping"]["identity_overlay_audit_sha256"] = artifact(audit_path)["sha256"]
        config["runtime_artifacts"].append(artifact(audit_path))
        validate_config(config)
        path = OUT / f"{case}-healthy-only.json"
        path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
        configurations[case] = artifact(path)
    preflight = {
        "schema_version": 1,
        "status": "isolated_adapter_built_real_hadoop_bytecode_verified_healthy_not_run",
        "no_minicluster_or_fault_trial_launched": True,
        "source_preflight": artifact(OUT / "preflight.json"),
        "audit_receipt": artifact(audit_path),
        "healthy_configs": configurations,
        "adapter_jar": receipt["adapter_jar"],
        "agent_jar": receipt["agent_jar"],
        "healthy_gate": preflight["healthy_gate"],
        "dispatch_gate": "One isolated healthy JUnit per case only, after HDFS lane admission; "
                         "no fault trial or full fuzz.",
    }
    (OUT / "build-preflight.json").write_text(json.dumps(preflight, indent=2,
                                                        sort_keys=True) + "\n")
    print(audited.stdout, end="")


if __name__ == "__main__":
    main()
