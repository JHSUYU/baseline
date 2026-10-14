#!/usr/bin/env python3
"""Bind the HDFS pipeline campaign to one fresh GraphChecker scope output."""

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
REQUEST = json.loads((HERE / "campaign-request-v1.json").read_text())
SCOPE_INPUT = json.loads((HERE / "scope-input-v1.json").read_text())
OLD = json.loads(Path(
    "/users/ZhenyuLi/baseline/data/mallory/graphchecker_port/imports/"
    "HDFS-32/49edf7055d5e4fd5-d9373a7b348a/config.json").read_text())


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope-output", type=Path, required=True)
    parser.add_argument("--weaver-jar", type=Path, required=True)
    parser.add_argument("--runtime-jar", type=Path, required=True)
    parser.add_argument("--graph-jar", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    source = Path(REQUEST["source"]["root"])
    for name in ("target", "junit"):
        file = source / REQUEST["source"][name + "_source"]
        if sha256(file) != REQUEST["source"][name + "_source_sha256"]:
            raise ValueError(f"source bytes changed: {file}")
    for jar in (args.weaver_jar, args.runtime_jar, args.graph_jar):
        if not jar.is_file():
            raise FileNotFoundError(jar)
    cp = SCOPE_INPUT["analysis"]["classpath"][0].split(":")
    if str(args.weaver_jar.resolve()) not in cp or str(args.runtime_jar.resolve()) not in cp:
        raise ValueError("weaver/runtime jars must be the exact static classpath entries")
    with ZipFile(args.runtime_jar) as archive:
        if ("edu/uva/liftlab/mallory/graphchecker/runtime/"
                "TargetThrowFingerprint.class") not in archive.namelist():
            raise ValueError("runtime jar lacks healthy target structural fingerprint")
    scope = args.scope_output.resolve()
    manifest = json.loads((scope / "weave_manifest.json").read_text())
    scope_map = scope / "static_scope_map.jsonl"
    if not scope_map.is_file():
        raise FileNotFoundError(scope_map)
    target_class = SCOPE_INPUT["target"]["class"]
    exception = SCOPE_INPUT["target"]["exception"]
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
    with scope_map.open() as stream:
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
    old_weaver, old_runtime = OLD["tool_classpath"][:2]
    tool = [str(args.weaver_jar.resolve()), str(args.runtime_jar.resolve())]
    tool += [x for x in OLD["tool_classpath"] if x not in (old_weaver, old_runtime)]
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
        "weave_manifest": str(scope / "weave_manifest.json"),
        "static_scope_map": str(scope_map),
        "original_class_dirs": [str(merged)],
        "soot_dependency_classpath": cp,
        "tool_classpath": tool,
        "test_classpath": OLD["test_classpath"],
        "graph_jar": str(args.graph_jar.resolve()),
        "cwd": REQUEST["source"]["root"],
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
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"config": str(args.out), "sha256": sha256(args.out),
                      "check_site_id": checks[0]["siteId"],
                      "throw_site_id": throws[0]["siteId"],
                      "static_value_edges": value_edges,
                      "generic_doors": len(manifest["doors"]),
                      "generic_rpc_ioexception_doors": len(rpc_doors)}))


if __name__ == "__main__":
    main()
