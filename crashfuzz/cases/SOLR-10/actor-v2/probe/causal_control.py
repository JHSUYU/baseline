#!/usr/bin/env python3
"""Isolated SOLR-40 cache-refresh causal control for the V4 watch-read fault.

Copies the Solr source and instrumented class directory before changing one
production method. The live V4 campaign's classes, JUnit and agent are never
modified. Run on the worker with enough disk for an embedded cluster.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from feedback import (atomic_json, checked_target_identity, events, io_identity,
                      runtime_actor, strict_sequence, target_after, target_relations)
from replay_candidate import persisted_alias


CASE = Path(__file__).resolve().parents[1]
SOURCE = CASE.parent / "work/solr-source"
CONTROL = Path.home() / "solr40-causal-control-v4"
OUT = CASE / "evidence/causal-control-v4"
ROUTE = Path("solr/core/src/java/org/apache/solr/update/processor/RoutedAliasUpdateProcessor.java")
JAVA_SOURCE = CASE / "generated" / ROUTE
JAVAC = "/usr/lib/jvm/java-8-openjdk-amd64/bin/javac"
PLAN = ("GET_DATA|/aliases.json|1|caller="
        "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#process:2312"
        "|actor=jetty:node3")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare() -> dict:
    CONTROL.mkdir(parents=True, exist_ok=True)
    source = CONTROL / "source"
    if not source.exists():
        source.mkdir()
        subprocess.run(["cp", "-a", "--reflink=auto", str(SOURCE) + "/.",
                        str(source)], check=True)
    source_head = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    assert source_head == json.loads((CASE / "build-receipt.json").read_text())["source_commit"]

    classes = CONTROL / "classes"
    if not classes.exists():
        shutil.copytree(CASE / "classes", classes)
    original_cp = (CASE / "classpath.txt").read_text().strip().split(":")
    assert original_cp[0] == str(CASE / "classes")
    (CONTROL / "classpath.txt").write_text(
        ":".join([str(classes), *original_cp[1:]]) + "\n")

    original = JAVA_SOURCE.read_text()
    before = ("    final Map<String, String> aliasProperties = "
              "zkController.getZkStateReader().getAliases().getCollectionAliasProperties(aliasName);\n"
              "    baseline.solr103940.FeedbackProbe.targetCheck(aliasProperties.isEmpty(), \"SOLR-40\",")
    after = ("    Map<String, String> aliasProperties = "
             "zkController.getZkStateReader().getAliases().getCollectionAliasProperties(aliasName);\n"
             "    if (aliasProperties.isEmpty()) {\n"
             "      try {\n"
             "        zkController.getZkStateReader().aliasesManager.update();\n"
             "      } catch (org.apache.zookeeper.KeeperException e) {\n"
             "        throw new SolrException(SolrException.ErrorCode.SERVER_ERROR, \"Alias cache refresh failed\", e);\n"
             "      } catch (InterruptedException e) {\n"
             "        Thread.currentThread().interrupt();\n"
             "        throw new SolrException(SolrException.ErrorCode.SERVER_ERROR, \"Alias cache refresh interrupted\", e);\n"
             "      }\n"
             "      aliasProperties = zkController.getZkStateReader().getAliases()"
             ".getCollectionAliasProperties(aliasName);\n"
             "    }\n"
             "    baseline.solr103940.FeedbackProbe.targetCheck(aliasProperties.isEmpty(), \"SOLR-40\",")
    if original.count(before) != 1:
        raise RuntimeError("Expected exactly one SOLR-40 pre-guard insertion site")
    patched = original.replace(before, after)
    route = source / ROUTE
    route.write_text(patched)
    compile_result = subprocess.run(
        [JAVAC, "-cp", (CONTROL / "classpath.txt").read_text().strip(),
         "-d", str(classes), str(route)], check=True, capture_output=True, text=True)

    runner = CONTROL / "probe/run.py"
    runner.parent.mkdir(exist_ok=True)
    runner_text = (CASE / "probe/run.py").read_text()
    runner_text = runner_text.replace(
        'SOURCE = CASE.parent / "work/solr-source"',
        'SOURCE = CASE / "source"')
    runner_text = runner_text.replace(
        'agent = CASE.parent / "work/lib/jacoco-agent.jar"',
        'agent = Path(' + repr(str(CASE.parent / "work/lib/jacoco-agent.jar")) + ')')
    assert 'SOURCE = CASE / "source"' in runner_text
    assert 'agent = Path(' in runner_text
    runner.write_text(runner_text)

    receipt = {
        "control": "refresh local AliasesManager cache once when SOLR-40 props are empty, then reread",
        "source_commit": source_head,
        "original_woven_route_sha256": digest(JAVA_SOURCE),
        "patched_woven_route_sha256": digest(route),
        "control_route_class_sha256": digest(classes / "org/apache/solr/update/processor/RoutedAliasUpdateProcessor.class"),
        "original_route_class_sha256": digest(CASE / "classes/org/apache/solr/update/processor/RoutedAliasUpdateProcessor.class"),
        "control_junit_class_sha256": digest(classes / "org/apache/solr/update/processor/TimeRoutedAliasUpdateProcessorTest.class"),
        "original_junit_class_sha256": digest(CASE / "classes/org/apache/solr/update/processor/TimeRoutedAliasUpdateProcessorTest.class"),
        "control_probe_class_sha256": digest(classes / "baseline/solr103940/FeedbackProbe.class"),
        "original_probe_class_sha256": digest(CASE / "classes/baseline/solr103940/FeedbackProbe.class"),
        "original_build_receipt_sha256": digest(CASE / "build-receipt.json"),
        "javac_stdout": compile_result.stdout,
        "javac_stderr": compile_result.stderr,
        "selector": PLAN,
        "control_directory": str(CONTROL),
    }
    assert receipt["control_junit_class_sha256"] == receipt["original_junit_class_sha256"]
    assert receipt["control_probe_class_sha256"] == receipt["original_probe_class_sha256"]
    assert receipt["control_route_class_sha256"] != receipt["original_route_class_sha256"]
    OUT.mkdir(parents=True, exist_ok=True)
    atomic_json(OUT / "build-receipt.json", receipt)
    return receipt


def run(count: int) -> None:
    receipt = prepare()
    summary_path = OUT / "summary.json"
    existing = json.loads(summary_path.read_text()).get("runs", []) if summary_path.exists() else []
    for number in range(len(existing) + 1, len(existing) + count + 1):
        run_dir = OUT / f"control-{number:03d}"
        proc = subprocess.run([sys.executable, str(CONTROL / "probe/run.py"),
                               str(run_dir), "--coverage", "--faults", PLAN,
                               "--timeout", "360"], check=False,
                              capture_output=True, text=True)
        trace = events(run_dir / "events.tsv")
        manifest = json.loads((run_dir / "manifest.json").read_text())
        applied = [event for event in trace if event["kind"] == "IO_APPLIED_CONNECTION_LOSS"]
        final = max((event["seq"] for event in applied), default=-1)
        reached, exception = target_after(trace, final)
        persisted, records = persisted_alias(run_dir / "scratch")
        refreshes = [event for event in trace
                     if (identity := io_identity(event)) is not None
                     and identity[0:2] == ("GET_DATA", "/aliases.json")
                     and "AliasesManager#update" in identity[2]
                     and event["seq"] > final]
        fault_actor = runtime_actor(applied[-1]) if applied else None
        same_reader_checks = [event for event in trace
                              if event["kind"] == "TARGET_CHECK"
                              and len(event["parts"]) > 1
                              and event["parts"][1] == "SOLR-40"
                              and event["seq"] > final
                              and runtime_actor(event) == fault_actor]
        first_same_reader = min((event["seq"] for event in same_reader_checks),
                                default=-1)
        same_reader_refresh_before_target = [
            event for event in refreshes
            if first_same_reader > event["seq"]
            and runtime_actor(event) == fault_actor]
        result = {
            "number": number, "selector": PLAN,
            "strict": strict_sequence([PLAN], trace) and checked_target_identity(trace),
            "postfault_target": reached["SOLR-40"],
            "target_exception": exception["SOLR-40"],
            "target_relations": target_relations(trace, final)["SOLR-40"],
            "postfault_refresh_getdata_count": len(refreshes),
            "same_reader_refresh_before_target": bool(same_reader_refresh_before_target),
            "same_reader_refresh_sequences": [event["seq"] for event in same_reader_refresh_before_target],
            "first_same_reader_target_sequence": first_same_reader,
            "persisted_alias_in_zk_txlog": persisted,
            "alias_txn_records": records,
            "junit_exit": manifest["exit_code"],
            "elapsed_seconds": manifest["elapsed_seconds"],
            "route_class_sha256": receipt["control_route_class_sha256"],
            "junit_class_sha256": receipt["control_junit_class_sha256"],
            "probe_class_sha256": receipt["control_probe_class_sha256"],
            "events_sha256": digest(run_dir / "events.tsv"),
            "junit_log_sha256": digest(run_dir / "junit.log"),
            "jacoco_sha256": digest(run_dir / "jacoco.exec"),
            "runner_exit": proc.returncode,
        }
        atomic_json(run_dir / "receipt.json", result)
        existing.append(result)
        atomic_json(summary_path, {"control": receipt["control"], "runs": existing})
        print(json.dumps({"control_run": number, "strict": result["strict"],
                          "target": result["postfault_target"],
                          "exception": result["target_exception"],
                          "same_reader_refresh_before_target": result["same_reader_refresh_before_target"],
                          "junit_exit": result["junit_exit"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.count <= 10:
        parser.error("count must be 1..10")
    run(args.count)
