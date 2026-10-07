#!/usr/bin/env python3
"""Trial481 control: exhaust real retry after its first collection-state fault."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from feedback import atomic_json, events, runtime_actor, checked_target_identity
from replay_candidate import persisted_alias


CASE = Path(__file__).resolve().parents[1]
SOURCE = CASE.parent / "work/solr-source"
CONTROL = Path.home() / "solr40-lowlevel-trial481-v9"
OUT = CASE / "evidence/lowlevel-trial481-v9"
STATE = CASE / "evidence/campaign-v4/state.json"
FROZEN_STATE_SHA = "46da0ad5b6e902346c69d4aae80f4e04f14ecf14b1cd2755ec166602e52c5cf4"
SOURCE_TRIAL = CASE / "evidence/campaign-v4/trial-481/trial.json"
ZKCLIENT = Path("solr/solrj/src/java/org/apache/solr/common/cloud/SolrZkClient.java")
JAVAC = "/usr/lib/jvm/java-8-openjdk-amd64/bin/javac"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(value: str, before: str, after: str) -> str:
    if value.count(before) != 1:
        raise RuntimeError(f"Expected one source insertion site, got {value.count(before)}")
    return value.replace(before, after)


def prepare() -> dict:
    assert digest(STATE) == FROZEN_STATE_SHA
    original = json.loads(SOURCE_TRIAL.read_text())
    assert original["strict"] and original["target_exception"]["SOLR-40"]
    assert len(original["plan"]) == 2
    assert original["plan"][0].startswith("EXISTS_WATCH|/collections/myalias")
    assert original["plan"][1].startswith("GET_DATA|/aliases.json")
    CONTROL.mkdir(parents=True, exist_ok=True)
    source = CONTROL / "source"
    source.mkdir(exist_ok=True)
    source_head = subprocess.check_output(
        ["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True).strip()
    assert source_head == json.loads((CASE / "build-receipt.json").read_text())["source_commit"]
    classes = CONTROL / "classes"
    if not classes.exists():
        shutil.copytree(CASE / "classes", classes)
    old_cp = (CASE / "classpath.txt").read_text().strip().split(":")
    assert old_cp[0] == str(CASE / "classes")
    cp = ":".join([str(classes), *old_cp[1:]])
    (CONTROL / "classpath.txt").write_text(cp + "\n")
    shutil.copy2(CASE / "build-receipt.json", CONTROL / "build-receipt.json")

    probe = (CASE / "probe/FeedbackProbe.java").read_text()
    extra = '''
  public static synchronized boolean isPhysicalRole(Object receiver, String role) {
    String node = NODE_BY_CLIENT.get(receiver);
    return node != null && role.equals(ROLE_BY_NODE.get(node));
  }

  public static synchronized boolean isFirstFaultApplied() {
    return "F0".equals(lastApplied);
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
        baseline.solr103940.FeedbackProbe.isPhysicalRole(this, "node1") &&
        baseline.solr103940.FeedbackProbe.isFirstFaultApplied() &&
        LOWLEVEL_WATCH_ONCE.compareAndSet(false, true);
    if (retryOnConnLoss) {
      return zkCmdExecutor.retryOperation(() -> {
        if (exhaustRetry) baseline.solr103940.FeedbackProbe.failUnderlyingAliasRead(path, this);
        return keeper.getData(path, wrapWatcher(watcher), stat);
      });
    } else {'''
    zkclient = replace_once(zkclient, before, after)
    java_source = source / ZKCLIENT
    java_source.parent.mkdir(parents=True, exist_ok=True)
    java_source.write_text(zkclient)
    subprocess.run([JAVAC, "-cp", cp, "-d", str(classes),
                    str(probe_source), str(java_source)], check=True)

    runner = CONTROL / "probe/run.py"
    runner_text = (CASE / "probe/run.py").read_text()
    runner_text = runner_text.replace('SOURCE = CASE.parent / "work/solr-source"',
                                      'SOURCE = Path(' + repr(str(SOURCE)) + ')')
    runner_text = runner_text.replace('agent = CASE.parent / "work/lib/jacoco-agent.jar"',
                                      'agent = Path(' + repr(str(CASE.parent / "work/lib/jacoco-agent.jar")) + ')')
    assert 'SOURCE = Path(' in runner_text and 'agent = Path(' in runner_text
    runner.write_text(runner_text)

    receipt = {
        "model": "Trial481 first EXISTS_WATCH fault followed by ConnectionLoss on every underlying alias watch getData retry for physical node1; normal retryOperation executes",
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
        "frozen_campaign_state_sha256": FROZEN_STATE_SHA,
        "first_fault_selector": original["plan"][0],
        "unmodified_second_selector": original["plan"][1],
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
        assert digest(STATE) == FROZEN_STATE_SHA
        assert shutil.disk_usage(CASE).free >= 8 * 1024 ** 3
        java_count = sum(line == "java" for line in subprocess.check_output(
            ["ps", "-eo", "comm="], text=True).splitlines())
        assert java_count < 5, f"Node has {java_count} Java processes"
        output = OUT / f"trial-{number:03d}"
        proc = subprocess.run([sys.executable, str(CONTROL / "probe/run.py"),
                               str(output), "--coverage", "--faults",
                               build["first_fault_selector"], "--timeout", "360"],
                              capture_output=True, text=True, check=False)
        trace = events(output / "events.tsv")
        manifest = json.loads((output / "manifest.json").read_text())
        attempts = [e for e in trace if e["kind"] == "IO_UNDERLYING_CONNECTION_LOSS"]
        first_faults = [e for e in trace if e["kind"] == "IO_APPLIED_CONNECTION_LOSS"]
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
            "first_app_fault_count": len(first_faults),
            "first_app_fault_precedes_underlying": bool(first_faults and attempts and
                first_faults[0]["seq"] < first_fault["seq"]),
            "first_app_fault_actor": runtime_actor(first_faults[0]) if first_faults else None,
            "one_live_reader": bool(attempts) and all(runtime_actor(e) == actor for e in attempts),
            "same_live_actor_for_both_phases": bool(first_faults and actor and
                runtime_actor(first_faults[0]) == actor),
            "target_identity_valid": checked_target_identity(trace),
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
            "frozen_campaign_state_sha256": FROZEN_STATE_SHA,
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
                          "same_actor": receipt["same_live_actor_for_both_phases"],
                          "same_reader_target": bool(targets),
                          "same_reader_exception": bool(exceptions),
                          "junit_exit": manifest["exit_code"]}), flush=True)
        assert digest(STATE) == FROZEN_STATE_SHA


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.count <= 3:
        parser.error("count must be 1..3")
    run(args.count)
