#!/usr/bin/env python3
"""Opt-in GraphChecker concolic weave using Mallory's pinned original sources.

This deliberately calls the original CausynthPipeline instead of translating
its root, branch, state and work-handoff hooks into Mallory's trace format.
The ordinary WeaveMain path and all existing campaign manifests are unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile


MALLORY = Path(__file__).resolve().parents[2]
ENGINE = Path(os.environ.get("MALLORY_NATIVE_ENGINE_ROOT") or
              MALLORY / "static_scope_port" / "original_engine").resolve()
REVISION = "c4a90033c654737206466ed36ce837c5b3c12457"
JAR = ENGINE / "target" / "mallory-original-graphchecker-seed-1.0-SNAPSHOT.jar"
ENGINE_RECEIPT = ENGINE / "target" / "native-original-engine-receipt.json"
DEPENDENCIES = ENGINE / "target" / "native-original-dependencies.txt"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def class_tree_digest(root: Path) -> str:
    classes = sorted(root.rglob("*.class"))
    if not classes:
        raise ValueError(f"class directory has no .class files: {root}")
    h = hashlib.sha256()
    for path in classes:
        h.update(path.relative_to(root).as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(bytes.fromhex(digest(path)))
    return h.hexdigest()


def file_tree_digest(root: Path) -> str:
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        raise ValueError(f"empty classpath directory: {root}")
    h = hashlib.sha256()
    for path in files:
        h.update(path.relative_to(root).as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(bytes.fromhex(digest(path)))
    return h.hexdigest()


def source_tree_digest() -> str:
    """Pin all compiled Mallory and vendored GraphChecker source inputs."""
    paths = [ENGINE / "pom.xml", ENGINE / "UPSTREAM_SOURCES.json"]
    paths.extend(sorted((ENGINE / "src" / "main" / "java").rglob("*.java")))
    paths.extend(sorted((ENGINE / "vendor" / "src" / "main" / "java").rglob("*.java")))
    paths.extend(sorted((ENGINE / "vendor" / "src" / "main" / "resources").rglob("*")))
    paths.extend(sorted((ENGINE / "src" / "main" / "resources").rglob("*")))
    h = hashlib.sha256()
    for path in paths:
        if path.is_file():
            h.update(path.relative_to(ENGINE).as_posix().encode("utf-8"))
            h.update(b"\0")
            h.update(bytes.fromhex(digest(path)))
    return h.hexdigest()


def dependency_digests(classpath: str) -> list[dict[str, str]]:
    rows = []
    for entry in filter(None, classpath.split(os.pathsep)):
        path = Path(entry).resolve(strict=True)
        if path.is_file():
            sha = digest(path)
        elif path.is_dir():
            sha = file_tree_digest(path)
        else:
            raise ValueError(f"unsupported classpath input: {path}")
        rows.append({"path": str(path), "sha256": sha})
    return rows


def main_class_digest(classpath: str, main_class: str) -> str:
    relative = main_class.replace(".", "/") + ".class"
    matches = []
    for entry in filter(None, classpath.split(os.pathsep)):
        path = Path(entry).resolve(strict=True)
        if path.is_dir() and (path / relative).is_file():
            matches.append(digest(path / relative))
        elif path.is_file() and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                if relative in archive.namelist():
                    matches.append(hashlib.sha256(archive.read(relative)).hexdigest())
    if len(matches) != 1:
        raise ValueError(f"post-weave main class must resolve uniquely: {main_class}")
    return matches[0]


def post_weave_spec(config: dict) -> dict | None:
    raw = config.get("post_weave")
    if raw is None:
        return None
    if (not isinstance(raw, dict) or not isinstance(raw.get("main_class"), str)
            or not raw["main_class"] or not isinstance(raw.get("classpath"), str)
            or not raw["classpath"] or not isinstance(raw.get("args"), list)
            or not all(isinstance(arg, str) for arg in raw["args"])):
        raise ValueError("post_weave needs main_class, classpath, and argv")
    if "GraphChecker/target/" in raw["classpath"]:
        raise ValueError("live GraphChecker/target artifact is forbidden")
    allowed = {"{woven_classes}", "{input_classes}"}
    if any("{" in arg or "}" in arg for arg in raw["args"]
           if arg not in allowed):
        raise ValueError("post_weave has an unknown placeholder")
    return raw


def prepare_engine() -> dict:
    """Build once per source revision; later case weaves only verify this receipt."""
    verified_vendor()
    ENGINE_RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["mvn", "-q", "-DskipTests", "package", "dependency:build-classpath",
         f"-Dmdep.outputFile={DEPENDENCIES}"],
        cwd=ENGINE, check=True,
    )
    if not JAR.is_file() or not DEPENDENCIES.is_file():
        raise ValueError("source build did not produce GraphChecker engine artifacts")
    dependencies = DEPENDENCIES.read_text().strip()
    receipt = {
        "schema_version": 1,
        "upstream_revision": REVISION,
        "source_tree_sha256": source_tree_digest(),
        "engine_jar_sha256": digest(JAR),
        "dependency_classpath": dependencies,
        "dependency_artifacts": dependency_digests(dependencies),
    }
    with tempfile.NamedTemporaryFile("w", dir=ENGINE_RECEIPT.parent,
                                     prefix="native-engine-", delete=False) as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    os.replace(temporary, ENGINE_RECEIPT)
    return receipt


def verify_engine() -> dict:
    verified_vendor()
    receipt = json.loads(ENGINE_RECEIPT.read_text())
    expected = {
        "upstream_revision": REVISION,
        "source_tree_sha256": source_tree_digest(),
        "engine_jar_sha256": digest(JAR),
        "dependency_classpath": DEPENDENCIES.read_text().strip(),
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise ValueError(f"GraphChecker source-built engine changed: {key}")
    if receipt.get("dependency_artifacts") != dependency_digests(
            receipt["dependency_classpath"]):
        raise ValueError("GraphChecker build dependencies changed")
    return receipt


def verified_vendor() -> dict:
    provenance = json.loads((ENGINE / "UPSTREAM_SOURCES.json").read_text())
    if provenance.get("upstreamRevision") != REVISION:
        raise ValueError("GraphChecker upstream revision differs")
    sources = provenance.get("sources", [])
    if len(sources) != provenance.get("sourceCount"):
        raise ValueError("incomplete GraphChecker source provenance")
    listed = {row["path"] for row in sources}
    vendor_root = ENGINE / "vendor" / "src" / "main" / "java"
    actual = {path.relative_to(vendor_root).as_posix()
              for path in vendor_root.rglob("*.java")}
    if listed != actual:
        raise ValueError("vendored GraphChecker sources differ from provenance")
    reviewed_runtime_adaptations = {
        "edu/uva/liftlab/graphchecker/runtime/CausynthTraceRecorder.java",
        # A selected nested region on another registered physical actor
        # opens its own occurrence instead of folding into its caller.
        "edu/uva/liftlab/graphchecker/runtime/Identity.java",
        "edu/uva/liftlab/graphchecker/runtime/MessageDoors.java",
        "edu/uva/liftlab/graphchecker/runtime/RowRuntime.java",
        "edu/uva/liftlab/graphchecker/runtime/RuntimeRegionPlanner.java",
    }
    for row in sources:
        copied = ENGINE / "vendor" / "src" / "main" / "java" / row["path"]
        if digest(copied) != row["copiedSha256"]:
            raise ValueError(f"vendored GraphChecker source changed: {row['path']}")
        if row.get("changed") and ("/runtime/" in row["path"]
                                   or row["path"].endswith("/contract/SessionReader.java")) \
                and row["path"] not in reviewed_runtime_adaptations:
            raise ValueError("unreviewed original runtime source modification")
    for row in provenance.get("resources", []):
        copied = ENGINE / "src" / "main" / "resources" / row["path"]
        if digest(copied) != row["copiedSha256"]:
            raise ValueError(f"vendored GraphChecker resource changed: {row['path']}")
    required = {
        "edu/uva/liftlab/graphchecker/runtime/ConcolicRegionRuntime.java",
        "edu/uva/liftlab/graphchecker/runtime/RowRuntime.java",
        "edu/uva/liftlab/graphchecker/runtime/SessionPublisher.java",
        "edu/uva/liftlab/graphchecker/runtime/Identity.java",
        "edu/uva/liftlab/graphchecker/contract/SessionReader.java",
        "edu/uva/liftlab/graphchecker/causynth/CausynthPipeline.java",
    }
    if not required.issubset({row["path"] for row in sources}):
        raise ValueError("required original GraphChecker hook source is absent")
    return provenance


def inputs(config_file: Path):
    config_file = config_file.resolve(strict=True)
    config = json.loads(config_file.read_text())
    weave_mode = config.get("weave_mode", "concolic")
    if weave_mode not in ("concolic", "region_state"):
        raise ValueError("weave_mode must be concolic or region_state")
    required = ("input_classes", "output_classes", "region_skeletons",
                "dependency_classpath", "java")
    if weave_mode == "concolic":
        required += ("task_plan", "task_id")
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise ValueError("missing native weave inputs: " + ", ".join(missing))
    if weave_mode == "region_state":
        artifacts = config.get("recording_artifacts")
        if not isinstance(artifacts, str) or not artifacts:
            raise ValueError("region_state weave requires recording_artifacts")
        if bool(config.get("task_plan")) != bool(config.get("task_id")):
            raise ValueError("region_state weave needs both task_plan and task_id or neither")
    jvm_args = config.get("jvm_args", [])
    if (not isinstance(jvm_args, list) or
            not all(isinstance(arg, str) and arg.startswith("-X") for arg in jvm_args)):
        raise ValueError("jvm_args must be a list of -X Java VM options")
    verified_vendor()
    source = Path(config["input_classes"]).resolve(strict=True)
    output = Path(config["output_classes"]).resolve()
    plan = (Path(config["task_plan"]).resolve(strict=True)
            if config.get("task_plan") else None)
    skeletons = Path(config["region_skeletons"]).resolve(strict=True)
    if not source.is_dir() or output == source or source in output.parents:
        raise ValueError("input_classes must be a separate class directory")
    extra = config["dependency_classpath"]
    for part in extra.split(os.pathsep):
        if part and "GraphChecker/target/" in Path(part).as_posix():
            raise ValueError("live GraphChecker/target artifact is forbidden")
    tool_classpath = config.get("tool_classpath")
    if tool_classpath is not None:
        if not isinstance(tool_classpath, str) or not tool_classpath:
            raise ValueError("tool_classpath must name Java tool dependencies")
        for part in tool_classpath.split(os.pathsep):
            if (not part or "GraphChecker/target/" in Path(part).as_posix()):
                raise ValueError("invalid tool_classpath entry")
        dependency_digests(tool_classpath)
    post_weave_spec(config)
    native_fault = config.get("native_fault_manifest")
    if native_fault is not None:
        if not isinstance(native_fault, str) or not native_fault:
            raise ValueError("native_fault_manifest must name a static manifest")
        Path(native_fault).resolve(strict=True)
    communication_mappings = config.get("communication_mappings")
    if communication_mappings is not None:
        if not isinstance(communication_mappings, str) or not communication_mappings:
            raise ValueError("communication_mappings must name a static mapping file")
        if not Path(communication_mappings).resolve(strict=True).is_file():
            raise ValueError("communication_mappings must be a file")
    process_dirs = config.get("process_dirs", [])
    if (not isinstance(process_dirs, list) or
            not all(isinstance(item, str) and item for item in process_dirs)):
        raise ValueError("process_dirs must be a list of class directories")
    for item in process_dirs:
        if not Path(item).resolve(strict=True).is_dir():
            raise ValueError(f"process directory is absent: {item}")
    return config, source, output, plan, skeletons


def run(config_file: Path) -> dict:
    config, source, output, plan, skeletons = inputs(config_file)
    engine = verify_engine()
    if output.exists() and any(output.iterdir()):
        raise ValueError("output_classes already contains files")
    output.mkdir(parents=True, exist_ok=True)
    extra = config["dependency_classpath"]
    classpath = os.pathsep.join(filter(None, (str(JAR),
                                             engine["dependency_classpath"],
                                             config.get("tool_classpath"), extra)))
    mode = config.get("weave_mode", "concolic")
    command = [str(Path(config["java"]).resolve(strict=True)),
               *config.get("jvm_args", [])]
    if mode == "concolic":
        command.extend(("-Dcausynth.instrument.concolic=true",
                        f"-Dcausynth.concolic.task.plan={plan}",
                        f"-Dcausynth.concolic.task.id={config['task_id']}"))
    else:
        artifacts = Path(config["recording_artifacts"]).resolve()
        if artifacts == output or artifacts == source:
            raise ValueError("recording_artifacts must be a separate directory")
        command.extend(("-Dcausynth.trace.mode=region-state",
                        f"-Dcausynth.output.dir={artifacts}"))
    command.append(f"-Dcausynth.region.skeletons={skeletons}")
    if config.get("native_fault_manifest"):
        command.append("-Dmallory.native.fault.manifest=" + str(
            Path(config["native_fault_manifest"]).resolve(strict=True)))
    if config.get("communication_mappings"):
        command.append("-Dcausynth.communication.mappings=" + str(
            Path(config["communication_mappings"]).resolve(strict=True)))
    if config.get("process_dirs"):
        command.append("-Dcausynth.process.dirs=" + os.pathsep.join(
            str(Path(item).resolve(strict=True)) for item in config["process_dirs"]))
    command.extend(["-cp", classpath,
                    "edu.uva.liftlab.graphchecker.GraphCheckerMain",
                    "-i", str(source), "-x", extra, "-o", str(output)])
    subprocess.run(command, check=True, timeout=int(config.get("timeout_seconds", 600)))
    post = post_weave_spec(config)
    post_receipt = None
    if post is not None:
        post_cp = post["classpath"]
        post_receipt = {
            "main_class": post["main_class"],
            "main_class_sha256": main_class_digest(post_cp, post["main_class"]),
            "dependency_artifacts": dependency_digests(post_cp),
        }
        replacements = {"{woven_classes}": str(output),
                        "{input_classes}": str(source)}
        post_command = [
            str(Path(config["java"]).resolve(strict=True)), "-cp", post_cp,
            post["main_class"],
            *(replacements.get(arg, arg) for arg in post["args"]),
        ]
        subprocess.run(post_command, check=True,
                       timeout=int(post.get("timeout_seconds", 180)))
    receipt = {
        "schema_version": 1,
        "mode": "mallory_vendored_original_graphchecker_" + mode + "_weave",
        "config_sha256": digest(config_file),
        "upstream_revision": REVISION,
        "engine_jar": str(JAR),
        "engine_jar_sha256": digest(JAR),
        "engine_receipt_sha256": digest(ENGINE_RECEIPT),
        "region_skeletons_sha256": digest(skeletons),
        "input_classes_sha256": class_tree_digest(source),
        "output_classes_sha256": class_tree_digest(output),
        "dependency_classpath_sha256": hashlib.sha256(
            config["dependency_classpath"].encode("utf-8")
        ).hexdigest(),
        "dependency_artifacts": dependency_digests(extra),
        "input_classes": str(source),
        "output_classes": str(output),
        "java_sha256": digest(Path(config["java"]).resolve(strict=True)),
        "post_weave": post_receipt,
        "original_hook_families": ["root", "branch", "state", "work_handoff"],
    }
    if plan is not None:
        receipt["task_plan_sha256"] = digest(plan)
        receipt["task_id"] = config["task_id"]
    if config.get("native_fault_manifest"):
        receipt["native_fault_manifest_sha256"] = digest(
            Path(config["native_fault_manifest"]).resolve(strict=True))
    if config.get("tool_classpath"):
        receipt["tool_classpath_artifacts"] = dependency_digests(
            config["tool_classpath"])
    if config.get("communication_mappings"):
        receipt["communication_mappings_sha256"] = digest(
            Path(config["communication_mappings"]).resolve(strict=True))
    if config.get("process_dirs"):
        receipt["process_dir_artifacts"] = dependency_digests(os.pathsep.join(
            config["process_dirs"]))
    if mode == "region_state":
        receipt["recording_artifacts_sha256"] = file_tree_digest(
            Path(config["recording_artifacts"]).resolve(strict=True))
    receipt_file = output / "native-original-weave-receipt.json"
    temporary = receipt_file.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, receipt_file)
    return receipt


def verify_existing(config_file: Path) -> dict:
    """Read-only pretrial gate: never runs Soot or changes the woven classes."""
    config, source, output, plan, skeletons = inputs(config_file)
    verify_engine()
    receipt = json.loads(
        (output / "native-original-weave-receipt.json").read_text()
    )
    observed = {
        "config_sha256": digest(config_file),
        "engine_jar_sha256": digest(JAR),
        "engine_receipt_sha256": digest(ENGINE_RECEIPT),
        "region_skeletons_sha256": digest(skeletons),
        "input_classes_sha256": class_tree_digest(source),
        "output_classes_sha256": class_tree_digest(output),
        "dependency_classpath_sha256": hashlib.sha256(
            config["dependency_classpath"].encode("utf-8")
        ).hexdigest(),
        "dependency_artifacts": dependency_digests(config["dependency_classpath"]),
        "java_sha256": digest(Path(config["java"]).resolve(strict=True)),
    }
    if plan is not None:
        observed["task_plan_sha256"] = digest(plan)
    elif (receipt.get("task_plan_sha256") is not None or
          receipt.get("task_id") is not None):
        raise ValueError("unexpected concolic task in task-free region weave receipt")
    if config.get("native_fault_manifest"):
        observed["native_fault_manifest_sha256"] = digest(
            Path(config["native_fault_manifest"]).resolve(strict=True))
    if config.get("tool_classpath"):
        observed["tool_classpath_artifacts"] = dependency_digests(
            config["tool_classpath"])
    elif receipt.get("tool_classpath_artifacts") is not None:
        raise ValueError("unexpected Java tool dependencies in receipt")
    if config.get("communication_mappings"):
        observed["communication_mappings_sha256"] = digest(
            Path(config["communication_mappings"]).resolve(strict=True))
    elif receipt.get("communication_mappings_sha256") is not None:
        raise ValueError("unexpected communication mappings in receipt")
    mode = config.get("weave_mode", "concolic")
    if mode == "region_state":
        observed["recording_artifacts_sha256"] = file_tree_digest(
            Path(config["recording_artifacts"]).resolve(strict=True))
    elif receipt.get("recording_artifacts_sha256") is not None:
        raise ValueError("unexpected recording artifacts in receipt")
    if config.get("process_dirs"):
        observed["process_dir_artifacts"] = dependency_digests(os.pathsep.join(
            config["process_dirs"]))
    post = post_weave_spec(config)
    if post is None:
        if receipt.get("post_weave") is not None:
            raise ValueError("unexpected post-weave adapter in receipt")
    else:
        expected_post = {
            "main_class": post["main_class"],
            "main_class_sha256": main_class_digest(
                post["classpath"], post["main_class"]),
            "dependency_artifacts": dependency_digests(post["classpath"]),
        }
        if receipt.get("post_weave") != expected_post:
            raise ValueError("post-weave adapter changed")
    if (receipt.get("schema_version") != 1 or
            receipt.get("mode") !=
            "mallory_vendored_original_graphchecker_" + mode + "_weave" or
            receipt.get("upstream_revision") != REVISION or
            receipt.get("input_classes") != str(source) or
            receipt.get("output_classes") != str(output)):
        raise ValueError("native weave receipt identity changed")
    for field, value in observed.items():
        if receipt.get(field) != value:
            raise ValueError(f"immutable native weave input changed: {field}")
    if plan is not None and receipt.get("task_id") != config["task_id"]:
        raise ValueError("native weave task id changed")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--prepare-engine", action="store_true",
                        help="build and pin the original GraphChecker engine once")
    parser.add_argument("--verify-only", action="store_true",
                        help="pretrial immutable receipt check; never invokes Soot")
    args = parser.parse_args()
    if args.prepare_engine:
        if args.config or args.verify_only:
            parser.error("--prepare-engine is a separate build step")
        print(json.dumps(prepare_engine(), sort_keys=True))
    else:
        if args.config is None:
            parser.error("--config is required for weave or verification")
        print(json.dumps(
            verify_existing(args.config) if args.verify_only else run(args.config),
            sort_keys=True,
        ))
