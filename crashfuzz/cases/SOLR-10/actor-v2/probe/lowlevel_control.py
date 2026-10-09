#!/usr/bin/env python3
"""Isolated control: exhaust SolrZkClient's built-in retry on one alias watch read."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from feedback import atomic_json, events, runtime_actor
from replay_candidate import persisted_alias


CASE = Path(__file__).resolve().parents[1]
SOURCE = CASE.parent / "work/solr-source"
CONTROL = Path.home() / "solr40-lowlevel-control-v4"
OUT = CASE / "evidence/lowlevel-control-v4"
ZKCLIENT = Path("solr/solrj/src/java/org/apache/solr/common/cloud/SolrZkClient.java")
JAVAC = "/usr/lib/jvm/java-8-openjdk-amd64/bin/javac"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(value: str, before: str, after: str) -> str:
    if value.count(before) != 1:
        raise RuntimeError(f"Expected one source insertion site, got {value.count(before)}")
    return value.replace(before, after)


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
    old_cp = (CASE / "classpath.txt").read_text().strip().split(":")
    assert old_cp[0] == str(CASE / "classes")
    cp = ":".join([str(classes), *old_cp[1:]])
    (CONTROL / "classpath.txt").write_text(cp + "\n")

    probe = (CASE / "probe/FeedbackProbe.java").read_text()
    extra = '''
  public static synchronized boolean isPhysicalRole(Object receiver, String role) {
    String node = NODE_BY_CLIENT.get(receiver);
    return node != null && role.equals(ROLE_BY_NODE.get(node));
  }

  public static synchronized void failUnderlyingAliasRead(String path, Object receiver)
      throws KeeperException.ConnectionLossException {
    String node = NODE_BY_CLIENT.get(receiver);
    Object manager = MANAGER_BY_CLIENT.get(receiver);
    String role = node == null ? null : ROLE_BY_NODE.get(node);
    event("IO_UNDERLYING_CONNECTION_LOSS", "GET_DATA\\t" + safe(path) +
        "\\tactor=jetty:" + safe(role) + "\\tnode=" + safe(node) +
        "\\tclient_id=" + System.identityHashCode(receiver) +
        "\\tmanager_id=" + System.identityHashCode(manager));
    throw new KeeperException.ConnectionLossException();
  }
'''
    probe = replace_once(probe, "  private FeedbackProbe() {}", extra + "\n  private FeedbackProbe() {}")
    probe_source = CONTROL / "probe/FeedbackProbe.java"
    probe_source.parent.mkdir(exist_ok=True)
    probe_source.write_text(probe)

    zkclient = (CASE / "generated" / ZKCLIENT).read_text()
    zkclient = replace_once(
        zkclient, "public class SolrZkClient implements Closeable {",
        "public class SolrZkClient implements Closeable {\n"
        "  private static final java.util.concurrent.atomic.AtomicBoolean LOWLEVEL_WATCH_ONCE = "
        "new java.util.concurrent.atomic.AtomicBoolean();")
    before = '''    baseline.solr103940.FeedbackProbe.io("GET_DATA", path, this);
    if (retryOnConnLoss) {
      return zkCmdExecutor.retryOperation(() -> keeper.getData(path, wrapWatcher(watcher), stat));
    } else {'''
    after = '''    baseline.solr103940.FeedbackProbe.io("GET_DATA", path, this);
    final boolean exhaustRetry = retryOnConnLoss && "/aliases.json".equals(path) &&
        watcher != null && watcher.getClass().getName().endsWith("$AliasesManager") &&
        baseline.solr103940.FeedbackProbe.isPhysicalRole(this, "node3") &&
        LOWLEVEL_WATCH_ONCE.compareAndSet(false, true);
    if (retryOnConnLoss) {
      return zkCmdExecutor.retryOperation(() -> {
        if (exhaustRetry) baseline.solr103940.FeedbackProbe.failUnderlyingAliasRead(path, this);
        return keeper.getData(path, wrapWatcher(watcher), stat);
      });
    } else {'''
    zkclient = replace_once(zkclient, before, after)
    java_source = source / ZKCLIENT
    java_source.write_text(zkclient)
    subprocess.run([JAVAC, "-cp", cp, "-d", str(classes),
                    str(probe_source), str(java_source)], check=True)

    runner = CONTROL / "probe/run.py"
    runner_text = (CASE / "probe/run.py").read_text()
    runner_text = runner_text.replace('SOURCE = CASE.parent / "work/solr-source"',
                                      'SOURCE = CASE / "source"')
    runner_text = runner_text.replace('agent = CASE.parent / "work/lib/jacoco-agent.jar"',
                                      'agent = Path(' + repr(str(CASE.parent / "work/lib/jacoco-agent.jar")) + ')')
    assert 'SOURCE = CASE / "source"' in runner_text and 'agent = Path(' in runner_text
    runner.write_text(runner_text)

    receipt = {
        "model": "ConnectionLoss on each underlying alias watch getData attempt until retryOperation exhausts",
        "source_commit": source_head,
        "injected_source_sha256": digest(java_source),
        "injected_probe_source_sha256": digest(probe_source),
        "zkclient_class_sha256": digest(classes / "org/apache/solr/common/cloud/SolrZkClient.class"),
        "probe_class_sha256": digest(classes / "baseline/solr103940/FeedbackProbe.class"),
        "route_class_sha256": digest(classes / "org/apache/solr/update/processor/RoutedAliasUpdateProcessor.class"),
        "original_route_class_sha256": digest(CASE / "classes/org/apache/solr/update/processor/RoutedAliasUpdateProcessor.class"),
        "junit_class_sha256": digest(classes / "org/apache/solr/update/processor/TimeRoutedAliasUpdateProcessorTest.class"),
        "original_junit_class_sha256": digest(CASE / "classes/org/apache/solr/update/processor/TimeRoutedAliasUpdateProcessorTest.class"),
        "original_build_receipt_sha256": digest(CASE / "build-receipt.json"),
        "control_directory": str(CONTROL),
    }
    assert receipt["route_class_sha256"] == receipt["original_route_class_sha256"]
    assert receipt["junit_class_sha256"] == receipt["original_junit_class_sha256"]
    OUT.mkdir(parents=True, exist_ok=True)
    atomic_json(OUT / "build-receipt.json", receipt)
    return receipt


def run(count: int) -> None:
    build = prepare()
    summary_path = OUT / "summary.json"
    existing = json.loads(summary_path.read_text()).get("runs", []) if summary_path.exists() else []
    for number in range(len(existing) + 1, len(existing) + count + 1):
        output = OUT / f"trial-{number:03d}"
        proc = subprocess.run([sys.executable, str(CONTROL / "probe/run.py"),
                               str(output), "--coverage", "--timeout", "360"],
                              capture_output=True, text=True, check=False)
        trace = events(output / "events.tsv")
        manifest = json.loads((output / "manifest.json").read_text())
        attempts = [e for e in trace if e["kind"] == "IO_UNDERLYING_CONNECTION_LOSS"]
        first_fault = attempts[0] if attempts else None
        last_fault = attempts[-1] if attempts else None
        actor = runtime_actor(first_fault) if first_fault else None
        targets = [e for e in trace if e["kind"] == "TARGET_CHECK"
                   and len(e["parts"]) > 1 and e["parts"][1] == "SOLR-40"
                   and last_fault and e["seq"] > last_fault["seq"]
                   and runtime_actor(e) == actor]
        during_retry_targets = [e for e in trace if e["kind"] == "TARGET_CHECK"
                                and len(e["parts"]) > 1 and e["parts"][1] == "SOLR-40"
                                and first_fault and last_fault
                                and first_fault["seq"] < e["seq"] < last_fault["seq"]
                                and runtime_actor(e) == actor]
        exceptions = [e for e in trace if e["kind"] == "TARGET_EXCEPTION"
                      and e["parts"] and e["parts"][0] == "SOLR-40"
                      and last_fault and e["seq"] > last_fault["seq"]
                      and runtime_actor(e) == actor]
        persisted, alias_records = persisted_alias(output / "scratch")
        receipt = {
            "number": number, "underlying_failures": len(attempts),
            "one_live_reader": bool(attempts) and all(runtime_actor(e) == actor for e in attempts),
            "fault_actor": actor,
            "postfault_same_reader_target": bool(targets),
            "during_retry_same_reader_target": bool(during_retry_targets),
            "during_retry_guard_values": [e["parts"][0] for e in during_retry_targets],
            "postfault_same_reader_exception": bool(exceptions),
            "target_guard_values": [e["parts"][0] for e in targets],
            "persisted_alias_in_zk_txlog": persisted,
            "alias_txn_records": alias_records,
            "junit_exit": manifest["exit_code"],
            "elapsed_seconds": manifest["elapsed_seconds"],
            "runner_exit": proc.returncode,
            "source_commit": build["source_commit"],
            "zkclient_class_sha256": build["zkclient_class_sha256"],
            "junit_class_sha256": build["junit_class_sha256"],
            "events_sha256": digest(output / "events.tsv"),
            "junit_log_sha256": digest(output / "junit.log"),
            "jacoco_sha256": digest(output / "jacoco.exec"),
        }
        atomic_json(output / "receipt.json", receipt)
        existing.append(receipt)
        atomic_json(summary_path, {"model": build["model"], "runs": existing})
        print(json.dumps({"trial": number, "underlying_failures": len(attempts),
                          "same_reader_target": bool(targets),
                          "same_reader_exception": bool(exceptions),
                          "junit_exit": manifest["exit_code"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.count <= 3:
        parser.error("count must be 1..3")
    run(args.count)
