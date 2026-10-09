#!/usr/bin/env python3
"""Compile and run an unchanged Solr Cloud JUnit with Mallory instrumentation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent
MALLORY = HERE.parents[1]
AGENT = MALLORY / "instrumentation" / "target" / "mallory-agent.jar"
ADAPTER = HERE / "target" / "mallory-solr-adapter.jar"
INVENTORY = MALLORY / "cases" / "inventory.json"


def selected_test(case_id: str) -> tuple[str, str, str, str | None]:
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    matches = [row for row in inventory["cases"]
               if row.get("case_id") == case_id and row.get("system") == "solr"]
    if len(matches) != 1:
        raise ValueError("not exactly one Solr inventory row for " + case_id)
    workload = matches[0]["workload"]
    selected = workload.get("selected_selector")
    source_path = workload.get("test_source_path")
    if not selected or "#" not in selected or not source_path:
        raise ValueError("no mapped Solr cluster test for " + case_id)
    test_class, test_method = selected.split("#", 1)
    matching = [candidate for candidate in workload.get("candidates", [])
                if candidate.get("selector") == selected and candidate.get("source_path") == source_path]
    expected_sha = matching[0].get("source_sha256") if len(matching) == 1 else None
    return test_class, test_method, source_path, expected_sha


def classpath(source: Path, distribution: Path, classes: Path) -> str:
    dist = distribution / "dist"
    first = [classes, source / "solr/core/src/test-files",
             dist / "solr-test-framework-8.11.4.jar",
             dist / "solr-core-8.11.4.jar", dist / "solr-solrj-8.11.4.jar",
             dist / "solr-analysis-extras-8.11.4.jar"]
    resources = [source / "solr/solrj/src/test-files"]
    groups = [dist / "test-framework/lib", dist / "test-framework/lucene-libs",
              distribution / "server/solr-webapp/webapp/WEB-INF/lib",
              distribution / "server/lib", distribution / "server/lib/ext",
              distribution / "contrib/analysis-extras/lib",
              distribution / "contrib/analysis-extras/lucene-libs"]
    jars = [jar for group in groups for jar in sorted(group.glob("*.jar"))]
    result = first + [path for path in resources if path.exists()] + jars
    missing = [str(path) for path in first if not path.exists()]
    if missing:
        raise FileNotFoundError("Solr distribution/classpath input missing: " + ", ".join(missing))
    return os.pathsep.join(str(path) for path in result)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_revision(case_id: str, source: Path) -> tuple[str, str]:
    """Identify the inventory-pinned commit without requiring copied .git data.

    Dispatch verifies every tracked source file against its clean reference
    before launching a copied worktree. The runner records that pinned commit;
    when Git metadata is present it also checks HEAD agrees with the pin.
    """
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    row = next(item for item in inventory["cases"] if item["case_id"] == case_id)
    pinned = row["provenance"]["source_commit"]
    command = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                             text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if command.returncode == 0:
        observed = command.stdout.strip()
        if observed != pinned:
            raise ValueError(f"source HEAD {observed} differs from inventory {pinned}")
        return pinned, "git_head_and_inventory"
    return pinned, "inventory_pinned_clean_copy_dispatch_fingerprint"


def compile_case(case_id: str, source: Path, distribution: Path, output: Path) -> dict:
    test_class, test_method, test_relative, expected_sha = selected_test(case_id)
    source, distribution, output = source.resolve(), distribution.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    classes = output / "classes"
    classes.mkdir(exist_ok=True)
    test_source = source / test_relative
    if not test_source.is_file():
        raise FileNotFoundError(test_source)
    if expected_sha and sha256(test_source) != expected_sha:
        raise ValueError("selected test source differs from inventory for " + case_id)
    cp = classpath(source, distribution, classes)
    build_env = os.environ.copy()
    build_env.pop("JAVA_TOOL_OPTIONS", None)
    sourcepath = os.pathsep.join(str(source / module) for module in
                                 ("solr/core/src/test", "solr/solrj/src/test")
                                 if (source / module).is_dir())
    subprocess.run(["javac", "-cp", cp, "-sourcepath", sourcepath,
                    "-d", str(classes),
                    str(test_source), str(HERE / "src/pilot/java/edu/uva/liftlab/mallory/solr/PilotJUnit.java")],
                   env=build_env, check=True)
    class_file = classes / (test_class.replace(".", "/") + ".class")
    if not class_file.is_file():
        raise FileNotFoundError("compiled selected JUnit class missing: " + str(class_file))
    return {"case_id": case_id, "test": test_class + "#" + test_method,
            "test_source_sha256": sha256(test_source),
            "compiled_test_class_sha256": sha256(class_file),
            "classpath": cp, "test_relative": test_relative}


def run(case_id: str, source: Path, distribution: Path, output: Path,
        timeout_seconds: int, campaign: bool = False,
        compile_only: bool = False) -> dict:
    source, distribution, output = source.resolve(), distribution.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    classes = output / "classes"
    scratch = output / "scratch"
    classes.mkdir(exist_ok=True)
    scratch.mkdir(exist_ok=True)
    built = compile_case(case_id, source, distribution, output)
    if compile_only:
        result = {key: value for key, value in built.items() if key != "classpath"}
        result["status"] = "compiled_only"
        (output / "pilot-result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return result
    test_class, test_method = built["test"].split("#", 1)
    test_relative = built["test_relative"]
    test_source = source / test_relative
    cp = built["classpath"]
    agent = Path(os.environ.get("MALLORY_SOLR_AGENT_JAR", str(AGENT))).resolve()
    adapter = Path(os.environ.get("MALLORY_SOLR_ADAPTER_JAR", str(ADAPTER))).resolve()
    if not agent.is_file() or not adapter.is_file():
        raise FileNotFoundError("agent jar or adapter jar missing")
    site_override = HERE / "cases" / case_id / "sites.json"
    sites = site_override if site_override.is_file() else MALLORY / "cases" / (case_id + ".sites.json")
    if not sites.is_file():
        raise FileNotFoundError("site file missing for " + case_id)
    config = output / "agent.properties"
    if campaign:
        if Path(os.environ.get("MALLORY_EVENT_FILE", "")).resolve() != output / "events.jsonl":
            raise ValueError("campaign output must match MALLORY_EVENT_FILE")
        if "JAVA_TOOL_OPTIONS" not in os.environ:
            raise ValueError("campaign requires JAVA_TOOL_OPTIONS from controller")
    else:
        config.write_text("\n".join([
            "run.id=" + case_id + "-healthy",
            "events=" + str(output / "events.jsonl"),
            "site.catalog=" + str(output / "site-catalog.jsonl"),
            "site.file=" + str(sites),
            "include=" + ",".join(json.loads((MALLORY / "cases" / (case_id + ".json")).read_text())
                                  .get("agent_include", [])),
            "adapter.jar=" + str(adapter),
            "adapter.transformer=edu.uva.liftlab.mallory.solr.SolrTransformer",
            "auto.io.doors=false", "coverage.methods=true", "coverage.branches=true",
            "state.fields=false", "state.maps=false", ""]), encoding="utf-8")
    module = test_relative.split("/src/test/")[0]
    command = ["java", "-ea", "-Xmx3g", "-Djava.awt.headless=true",
               "-Djava.io.tmpdir=" + str(scratch), "-DtempDir=" + str(scratch),
               "-Dtests.seed=F0993D5343E20BA4", "-Dtests.src.home=" + str(source / module),
               "-Dcommon.dir=" + str(source / "lucene"), "-Dtests.asserts=true",
               "-Dtests.slow=true", "-Dtests.nightly=" + ("true" if os.environ.get("MALLORY_SOLR_NIGHTLY") == "1" else "false"), "-Dtests.timeoutSuite=86400000",
               "-Dtests.timeout=86400000",
               "-Dtests.awaitsfix=" + ("true" if os.environ.get("MALLORY_SOLR_AWAITSFIX") == "1" else "false"),
               "-Djetty.testMode=1", "-Djetty.insecurerandom=1",
               "-Dsolr.directoryFactory=org.apache.solr.core.MockDirectoryFactory",
               "-Djdk.map.althashing.threshold=0", "-Djava.security.egd=file:/dev/./urandom",
               ]
    if not campaign:
        command.append("-javaagent:" + str(agent) + "=config=" + str(config))
    command.extend(["-cp", cp, "edu.uva.liftlab.mallory.solr.PilotJUnit", test_class, test_method])
    started = time.monotonic()
    with (output / "junit.log").open("w", encoding="utf-8") as log:
        try:
            completed = subprocess.run(command, cwd=source, stdout=log, stderr=subprocess.STDOUT,
                                       timeout=timeout_seconds, check=False)
            exit_code = completed.returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
            log.write("\nMALLORY_TEST_TIMEOUT\n")
    events = []
    trace = output / "events.jsonl"
    if trace.is_file():
        for line in trace.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                break
    checks = [row for row in events if row.get("type") == "TARGET_CHECK"]
    throws = [row for row in events if row.get("type") == "TARGET_THROW"]
    log_text = (output / "junit.log").read_text(encoding="utf-8", errors="replace")
    junit = re.search(r"MALLORY_TEST_RESULT run=(\d+) failures=(\d+) ignored=(\d+)", log_text)
    revision, revision_basis = source_revision(case_id, source)
    result = {
        "schema_version": 1, "case_id": case_id, "phase": "healthy_seed",
        "system": "solr", "system_version": "8.11.4",
        "source_revision": revision, "source_revision_basis": revision_basis,
        "nightly_enabled": os.environ.get("MALLORY_SOLR_NIGHTLY") == "1",
        "awaitsfix_enabled": os.environ.get("MALLORY_SOLR_AWAITSFIX") == "1",
        "test": test_class + "#" + test_method, "test_source_sha256": sha256(test_source),
        "agent_sha256": sha256(agent), "adapter_sha256": sha256(adapter),
        "exit_code": exit_code, "elapsed_seconds": round(time.monotonic() - started, 3),
        "junit": ({"run": int(junit[1]), "failures": int(junit[2]), "ignored": int(junit[3])}
                  if junit else None),
        "target_check_count": len(checks), "target_throw_count": len(throws),
        "target_nodes": sorted({str(row.get("node")) for row in checks}),
        "target_occurrences": sorted({str(row.get("occurrence")) for row in checks}),
        "status": ("healthy_calibrated" if exit_code == 0 and junit and int(junit[1]) >= 1
                   and len(checks) > 0 and all(row.get("node") not in (None, "unknown")
                                               and row.get("region") for row in checks)
                   else "failed_calibration"),
    }
    (output / "pilot-result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("case_id")
    parser.add_argument("--source", type=Path,
                        default=Path.home() / ".mallory-worktrees/solr")
    parser.add_argument("--distribution", type=Path,
                        default=Path.home() / ".baseline-deps/solr-8.11.4")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=420)
    parser.add_argument("--campaign", action="store_true",
                        help="accept controller JAVA_TOOL_OPTIONS and MALLORY_* paths")
    parser.add_argument("--compile-only", action="store_true",
                        help="verify that the selected unchanged JUnit compiles; do not run the test")
    args = parser.parse_args()
    result = run(args.case_id, args.source, args.distribution,
                 args.output, args.timeout, args.campaign, args.compile_only)
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(result.get("exit_code", 0))
