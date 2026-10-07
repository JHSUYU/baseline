#!/usr/bin/env python3
"""Bounded SOLR-40 control: one underlying alias read failure, then real retry.

Run only after the original V4 campaign has reached an atomic terminal state.
The original JUnit and routed-alias classes remain byte-identical. This
separate build changes SolrZkClient solely to inject one ConnectionLoss from
the underlying ZooKeeper read and record when retryOperation returns.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import lowlevel_trial481_control as earlier
from feedback import atomic_json, checked_target_identity, events, runtime_actor
from replay_candidate import persisted_alias


CASE = Path(__file__).resolve().parents[1]
STATE = CASE / "evidence/campaign-v4/state.json"
CONTROL = Path.home() / "solr40-lowlevel-single-retry-v10"
OUT = CASE / "evidence/lowlevel-single-retry-v10"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def terminal_state_sha() -> str:
    state = json.loads(STATE.read_text())
    if state["inflight"] is not None or any(
            item["stop_reason"] == "running" for item in state["site_progress"].values()):
        raise RuntimeError("The unchanged V4 campaign must finish first")
    return sha(STATE)


def prepare(frozen_sha: str) -> dict:
    # Reuse the previously reviewed isolated classpath and exact trial481
    # selector preparation, without changing its frozen raw evidence.
    earlier.STATE = STATE
    earlier.FROZEN_STATE_SHA = frozen_sha
    earlier.CONTROL = CONTROL
    earlier.OUT = OUT
    build = earlier.prepare()
    java_source = CONTROL / "source" / earlier.ZKCLIENT
    content = java_source.read_text()
    content = earlier.replace_once(
        content,
        "private static final java.util.concurrent.atomic.AtomicBoolean LOWLEVEL_WATCH_ONCE = new java.util.concurrent.atomic.AtomicBoolean();",
        "private static final java.util.concurrent.atomic.AtomicBoolean LOWLEVEL_WATCH_ONCE = new java.util.concurrent.atomic.AtomicBoolean();\n"
        "  private static final java.util.concurrent.atomic.AtomicBoolean LOWLEVEL_FAIL_ONCE = new java.util.concurrent.atomic.AtomicBoolean();")
    content = earlier.replace_once(
        content,
        """      return zkCmdExecutor.retryOperation(() -> {
        if (exhaustRetry) baseline.solr103940.FeedbackProbe.failUnderlyingAliasRead(path, this);
        return keeper.getData(path, wrapWatcher(watcher), stat);
      });""",
        """      byte[] result = zkCmdExecutor.retryOperation(() -> {
        if (exhaustRetry && LOWLEVEL_FAIL_ONCE.compareAndSet(false, true))
          baseline.solr103940.FeedbackProbe.failUnderlyingAliasRead(path, this);
        return keeper.getData(path, wrapWatcher(watcher), stat);
      });
      if (exhaustRetry) baseline.solr103940.FeedbackProbe.aliasRetrySuccess(path, this);
      return result;""")
    java_source.write_text(content)

    probe_source = CONTROL / "probe/FeedbackProbe.java"
    probe = probe_source.read_text()
    probe = earlier.replace_once(probe, "  private FeedbackProbe() {}", '''
  public static synchronized void aliasRetrySuccess(String path, Object receiver) {
    String node = NODE_BY_CLIENT.get(receiver);
    Object manager = MANAGER_BY_CLIENT.get(receiver);
    String role = node == null ? null : ROLE_BY_NODE.get(node);
    event("IO_UNDERLYING_RETRY_SUCCESS", "GET_DATA\\t" + safe(path) +
        "\\tactor=jetty:" + safe(role) + "\\tnode=" + safe(node) +
        "\\tclient_id=" + System.identityHashCode(receiver) +
        "\\tmanager_id=" + System.identityHashCode(manager));
  }

  private FeedbackProbe() {}''')
    probe_source.write_text(probe)
    classes = CONTROL / "classes"
    cp = (CONTROL / "classpath.txt").read_text().strip()
    subprocess.run([earlier.JAVAC, "-cp", cp, "-d", str(classes),
                    str(probe_source), str(java_source)], check=True)
    build.update({
        "model": "one underlying ConnectionLoss on alias watch getData, then genuine retryOperation and ZooKeeper read",
        "frozen_campaign_state_sha256": frozen_sha,
        "injected_source_sha256": sha(java_source),
        "injected_probe_source_sha256": sha(probe_source),
        "zkclient_class_sha256": sha(classes / "org/apache/solr/common/cloud/SolrZkClient.class"),
        "probe_class_sha256": sha(classes / "baseline/solr103940/FeedbackProbe.class"),
        "route_class_sha256": sha(classes / "org/apache/solr/update/processor/RoutedAliasUpdateProcessor.class"),
        "junit_class_sha256": sha(classes / "org/apache/solr/update/processor/TimeRoutedAliasUpdateProcessorTest.class"),
    })
    if build["route_class_sha256"] != build["original_route_class_sha256"] or \
            build["junit_class_sha256"] != build["original_junit_class_sha256"]:
        raise RuntimeError("Original workload or target class changed")
    atomic_json(OUT / "build-receipt.json", build)
    return build


def run(count: int) -> None:
    frozen_sha = terminal_state_sha()
    build = prepare(frozen_sha)
    summary_path = OUT / "summary.json"
    rows = json.loads(summary_path.read_text()).get("runs", []) if summary_path.exists() else []
    for number in range(len(rows) + 1, len(rows) + count + 1):
        if sha(STATE) != frozen_sha or shutil.disk_usage(CASE).free < 8 * 1024 ** 3:
            raise RuntimeError("Original checkpoint changed or disk guard tripped")
        java_count = sum(line == "java" for line in subprocess.check_output(
            ["ps", "-eo", "comm="], text=True).splitlines())
        if java_count >= 5:
            raise RuntimeError(f"No isolated JVM slot ({java_count} Java processes)")
        output = OUT / f"trial-{number:03d}"
        proc = subprocess.run([sys.executable, str(CONTROL / "probe/run.py"),
                               str(output), "--coverage", "--faults",
                               build["first_fault_selector"], "--timeout", "360"],
                              capture_output=True, text=True, check=False)
        trace = events(output / "events.tsv")
        manifest = json.loads((output / "manifest.json").read_text())
        entry_faults = [e for e in trace if e["kind"] == "IO_APPLIED_CONNECTION_LOSS"]
        low_faults = [e for e in trace if e["kind"] == "IO_UNDERLYING_CONNECTION_LOSS"]
        successes = [e for e in trace if e["kind"] == "IO_UNDERLYING_RETRY_SUCCESS"]
        actor = runtime_actor(low_faults[0]) if low_faults else None
        guards = [e for e in trace if e["kind"] == "TARGET_CHECK" and
                  len(e["parts"]) > 1 and e["parts"][1] == "SOLR-40" and
                  low_faults and e["seq"] > low_faults[0]["seq"] and
                  runtime_actor(e) == actor]
        throws = [e for e in trace if e["kind"] == "TARGET_EXCEPTION" and
                  e["parts"] and e["parts"][0] == "SOLR-40" and
                  low_faults and e["seq"] > low_faults[0]["seq"] and
                  runtime_actor(e) == actor]
        success_seq = successes[0]["seq"] if successes else None
        persisted, records = persisted_alias(output / "scratch")
        receipt = {
            "number": number, "model": build["model"],
            "entry_fault_count": len(entry_faults), "underlying_failure_count": len(low_faults),
            "retry_success_count": len(successes), "low_fault_actor": actor,
            "same_reader_entry_and_underlying": bool(entry_faults and low_faults and
                runtime_actor(entry_faults[0]) == actor),
            "target_identity_valid": checked_target_identity(trace),
            "same_reader_guard_after_failure": bool(guards),
            "same_reader_throw_after_failure": bool(throws),
            "guard_before_retry_success": bool(success_seq and any(e["seq"] < success_seq for e in guards)),
            "throw_before_retry_success": bool(success_seq and any(e["seq"] < success_seq for e in throws)),
            "guard_after_retry_success": bool(success_seq and any(e["seq"] > success_seq for e in guards)),
            "throw_after_retry_success": bool(success_seq and any(e["seq"] > success_seq for e in throws)),
            "persisted_alias_in_zk_txlog": persisted, "alias_txn_records": records,
            "junit_exit": manifest["exit_code"], "elapsed_seconds": manifest["elapsed_seconds"],
            "runner_exit": proc.returncode, "frozen_campaign_state_sha256": frozen_sha,
            "events_sha256": sha(output / "events.tsv"),
            "junit_log_sha256": sha(output / "junit.log"),
            "jacoco_sha256": sha(output / "jacoco.exec"),
        }
        atomic_json(output / "receipt.json", receipt)
        rows.append(receipt)
        atomic_json(summary_path, {"model": build["model"], "runs": rows})
        print(json.dumps({"trial": number, "underlying": len(low_faults),
                          "retry_success": len(successes), "same_reader_throw": bool(throws),
                          "throw_before_success": receipt["throw_before_retry_success"],
                          "junit_exit": manifest["exit_code"]}), flush=True)
        if sha(STATE) != frozen_sha:
            raise RuntimeError("Original campaign checkpoint changed during the control")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.count <= 5:
        parser.error("count must be 1..5")
    run(args.count)
