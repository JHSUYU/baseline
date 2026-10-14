#!/usr/bin/env python3
"""Bind the HDFS pipeline campaign to one fresh GraphChecker scope output."""

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
REQUEST = json.loads((HERE / "campaign-request-v1.json").read_text())
DEFAULT_REFERENCE = Path(
    "/users/ZhenyuLi/baseline/data/mallory/graphchecker_port/imports/"
    "HDFS-32/49edf7055d5e4fd5-d9373a7b348a/config.json")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope-output", type=Path, required=True)
    parser.add_argument("--scope-input", type=Path,
                        default=HERE / "scope-input-v1.json")
    parser.add_argument("--source-root", type=Path,
                        default=Path(REQUEST["source"]["root"]))
    parser.add_argument("--reference-config", type=Path,
                        default=DEFAULT_REFERENCE)
    parser.add_argument("--weaver-jar", type=Path, required=True)
    parser.add_argument("--runtime-jar", type=Path, required=True)
    parser.add_argument("--graph-jar", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    source = args.source_root.resolve()
    scope_input = json.loads(args.scope_input.read_text())
    reference = json.loads(args.reference_config.read_text())
    for name in ("target", "junit"):
        file = source / REQUEST["source"][name + "_source"]
        if sha256(file) != REQUEST["source"][name + "_source_sha256"]:
            raise ValueError(f"source bytes changed: {file}")
    for jar in (args.weaver_jar, args.runtime_jar, args.graph_jar):
        if not jar.is_file():
            raise FileNotFoundError(jar)
    cp = scope_input["analysis"]["classpath"][0].split(":")
    if str(args.weaver_jar.resolve()) not in cp or str(args.runtime_jar.resolve()) not in cp:
        raise ValueError("weaver/runtime jars must be the exact static classpath entries")
    with ZipFile(args.runtime_jar) as archive:
        if ("edu/uva/liftlab/mallory/graphchecker/runtime/"
                "TargetThrowFingerprint.class") not in archive.namelist():
            raise ValueError("runtime jar lacks healthy target structural fingerprint")
    scope = args.scope_output.resolve()
    manifest_file = scope / "graphchecker_weave_manifest.json"
    manifest = json.loads(manifest_file.read_text())
    scope_map = scope / "graphchecker_static_scope_map.jsonl"
    may_map = scope / "static_scope_map.jsonl"
    for path in (scope_map, may_map):
        if not path.is_file():
            raise FileNotFoundError(path)
    target_class = scope_input["target"]["class"]
    exception = scope_input["target"]["exception"]
    targets = manifest["targets"]
    checks = [x for x in targets if x.get("clazz") == target_class and
              x.get("method") == "retrieveDataEncryptionKey" and
              x.get("kind") == "BRANCH" and x.get("line") == 552]
    throws = [x for x in targets if x.get("clazz") == target_class and
              x.get("method") == "retrieveDataEncryptionKey" and
              x.get("kind") == "THROW" and x.get("line") == 555 and
              x.get("exceptionClass") == exception]
    if len(checks) != 1 or len(throws) != 1:
        raise ValueError("fresh manifest lacks unique check/throw mapping")
    digest = hashlib.sha256(":".join(cp).encode()).hexdigest()
    if manifest.get("sootDependencyClasspathSha256") != digest:
        raise ValueError("fresh Soot classpath differs from staged input")
    if not all(Path(x).exists() for x in cp):
        raise ValueError("fresh Soot classpath has missing entry")
    with may_map.open() as stream:
        value_edges = sum(1 for line in stream if line.strip() and
                          json.loads(line).get("role") == "STATIC_VALUE_EDGE")
    if value_edges < 1:
        raise ValueError("fresh GraphChecker scope has no value edge")
    if not manifest.get("doors"):
        raise ValueError("fresh GraphChecker scope has no generic fault doors")
    rpc_doors = [door for door in manifest["doors"]
                 if "org.apache.hadoop.ipc." in door.get("callee", "") and
                 door.get("exceptionClass") == "java.io.IOException"]
    if not rpc_doors:
        raise ValueError("fresh scope lacks generic Hadoop RPC IOException doors")
    merged = Path(cp[0])
    target_class_file = merged / target_class.replace(".", "/")
    target_class_file = target_class_file.with_suffix(".class")
    if sha256(target_class_file) != REQUEST["source"][
            "compiled_target_class_sha256_expected_inventory"]:
        raise ValueError("compiled target class differs from inventory pin")
    old_weaver, old_runtime = reference["tool_classpath"][:2]
    tool = [str(args.weaver_jar.resolve()), str(args.runtime_jar.resolve())]
    tool += [x for x in reference["tool_classpath"] if x not in (old_weaver, old_runtime)]
    template = args.out.parent / "trial-cwd-template"
    if template.exists():
        raise FileExistsError(template)
    (template / "logs").mkdir(parents=True)
    (template / "test-data").mkdir()
    config = {
        "schema_version": 1, "case_id": REQUEST["version"],
        "junit": REQUEST["junit"],
        "target": {"check_site_id": checks[0]["siteId"],
                   "throw_site_id": throws[0]["siteId"],
                   "exception_class": exception},
        "weave_manifest": str(manifest_file),
        "static_scope_map": str(scope_map),
        "static_may_scope_map": str(may_map),
        "original_class_dirs": [str(merged)],
        "soot_dependency_classpath": cp,
        "tool_classpath": tool,
        "test_classpath": reference["test_classpath"],
        "graph_jar": str(args.graph_jar.resolve()),
        "cwd": str(source),
        "java": "/usr/lib/jvm/java-8-openjdk-amd64/bin/java",
        "runner": {"main_class":
                   "edu.uva.liftlab.mallory.graphchecker.weave.JUnitTrialMain",
                   "args": ["{class}", "{method}", "{parameter_index}"],
                   "jvm_args": ["-Xmx4g", "-ea",
                                "-Dhadoop.log.dir={trial_cwd}/logs",
                                "-Dtest.build.data={trial_cwd}/test-data"]},
        "budget": {key: REQUEST["budget"][key] for key in
                   ("fault_trials", "seconds", "max_faults_per_trial")},
        "timeout_seconds": REQUEST["budget"]["trial_timeout_seconds"],
        "scratch_root": "/dev/shm",
        "trial_cwd_template": str(template.resolve()),
        "capacity_guard": {
            "pg0_path": "/proj/silentfailure-PG0",
            "pg0_start_min_bytes": REQUEST["capacity"]["start_available_bytes_at_least"],
            "pg0_stop_max_bytes": REQUEST["capacity"]["stop_available_bytes_at_or_below"],
            "root_path": "/",
            "root_min_bytes": 1073741824,
            "scratch_path": "/dev/shm",
            "scratch_min_bytes": 1073741824,
            "memory_min_bytes": 17179869184,
            "private_max_bytes": 4831838208,
            "durable_path": "/proj/silentfailure-PG0/ZhenyuLi/Mallory/"
                            "campaigns/HDFS-11-PIPELINE-GC-V1",
            "durable_max_bytes": REQUEST["capacity"][
                "per_campaign_durable_pg0_cap_bytes"],
            "poll_seconds": 3,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"config": str(args.out), "sha256": sha256(args.out),
                      "check_site_id": checks[0]["siteId"],
                      "throw_site_id": throws[0]["siteId"],
                      "static_value_edges": value_edges,
                      "graphchecker_map_sha256": sha256(scope_map),
                      "static_may_sidecar_sha256": sha256(may_map),
                      "generic_doors": len(manifest["doors"]),
                      "generic_rpc_ioexception_doors": len(rpc_doors)}))


if __name__ == "__main__":
    main()
