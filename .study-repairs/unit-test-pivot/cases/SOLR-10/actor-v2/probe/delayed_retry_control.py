#!/usr/bin/env python3
"""Timing control: evaluate the SOLR-40 guard after the real alias-read retry.

The original JUnit is byte-identical. In this isolated control only, add a
bounded wait immediately before getAliasProps reads the alias cache. This
changes timing deliberately and cannot itself establish production behavior.
"""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

import lowlevel_single_retry as base
import lowlevel_trial481_control as earlier
from feedback import atomic_json, checked_target_identity, events, runtime_actor
from replay_candidate import persisted_alias


CASE = Path(__file__).resolve().parents[1]
CONTROL = Path.home() / "solr40-delayed-retry-v11b"
OUT = CASE / "evidence/delayed-retry-v11b"
STATE = CASE / "evidence/campaign-v4/state.json"
ROUTE = Path("solr/core/src/java/org/apache/solr/update/processor/RoutedAliasUpdateProcessor.java")


def prepare() -> dict:
    frozen = base.terminal_state_sha()
    base.CONTROL = CONTROL
    base.OUT = OUT
    build = base.prepare(frozen)
    probe_source = CONTROL / "probe/FeedbackProbe.java"
    probe = probe_source.read_text()
    probe = earlier.replace_once(probe, "  private FeedbackProbe() {}", '''
  private static volatile Object DELAY_CLIENT;
  private static volatile boolean DELAY_RETRY_COMPLETE;

  public static void awaitAliasRetry(Object client) {
    if (DELAY_CLIENT != client || DELAY_RETRY_COMPLETE) return;
    long deadline = System.nanoTime() + java.util.concurrent.TimeUnit.SECONDS.toNanos(4);
    while (!DELAY_RETRY_COMPLETE && System.nanoTime() < deadline) {
      try { Thread.sleep(5); }
      catch (InterruptedException error) { Thread.currentThread().interrupt(); break; }
    }
    boolean complete = DELAY_RETRY_COMPLETE;
    if (complete) {
      try { Thread.sleep(100); }
      catch (InterruptedException error) { Thread.currentThread().interrupt(); }
    }
    synchronized (FeedbackProbe.class) {
      event("TARGET_DELAY_GATE", "client_id=" + System.identityHashCode(client) +
          "\\tretry_complete=" + complete);
    }
  }

  private FeedbackProbe() {}''')
    probe = earlier.replace_once(probe,
        '    event("IO_UNDERLYING_CONNECTION_LOSS", "GET_DATA\\t" + safe(path) +',
        '    DELAY_CLIENT = receiver;\n    DELAY_RETRY_COMPLETE = false;\n'
        '    event("IO_UNDERLYING_CONNECTION_LOSS", "GET_DATA\\t" + safe(path) +')
    probe = earlier.replace_once(probe,
        '    event("IO_UNDERLYING_RETRY_SUCCESS", "GET_DATA\\t" + safe(path) +',
        '    if (DELAY_CLIENT == receiver) DELAY_RETRY_COMPLETE = true;\n'
        '    event("IO_UNDERLYING_RETRY_SUCCESS", "GET_DATA\\t" + safe(path) +')
    probe_source.write_text(probe)

    route_source = CONTROL / "source" / ROUTE
    route_source.parent.mkdir(parents=True, exist_ok=True)
    route = (CASE / "generated" / ROUTE).read_text()
    route = earlier.replace_once(route,
        '    ZkController zkController = req.getCoreContainer().getZkController();\n'
        '    final Map<String, String> aliasProperties =',
        '    ZkController zkController = req.getCoreContainer().getZkController();\n'
        '    baseline.solr103940.FeedbackProbe.awaitAliasRetry('
        'zkController.getZkStateReader().getZkClient());\n'
        '    final Map<String, String> aliasProperties =')
    route_source.write_text(route)
    cp = (CONTROL / "classpath.txt").read_text().strip()
    subprocess.run([earlier.JAVAC, "-cp", cp, "-d", str(CONTROL / "classes"),
                    str(probe_source), str(route_source)], check=True)
    build.update({
        "model": "same F0 plus one underlying alias read failure; bounded guard wait until retry completion",
        "timing_control_only": True,
        "timing_limit_seconds": 4,
        "wait_after_retry_success_millis": 100,
        "timing_probe_source_sha256": base.sha(probe_source),
        "timing_route_source_sha256": base.sha(route_source),
        "timing_probe_class_sha256": base.sha(CONTROL / "classes" /
            "baseline/solr103940/FeedbackProbe.class"),
        "timing_zkclient_class_sha256": base.sha(CONTROL / "classes" /
            "org/apache/solr/common/cloud/SolrZkClient.class"),
        "timing_route_class_sha256": base.sha(CONTROL / "classes" /
                                               "org/apache/solr/update/processor/RoutedAliasUpdateProcessor.class"),
        "junit_class_sha256": base.sha(CONTROL / "classes" /
                                       "org/apache/solr/update/processor/TimeRoutedAliasUpdateProcessorTest.class"),
    })
    if build["junit_class_sha256"] != build["original_junit_class_sha256"]:
        raise RuntimeError("Original JUnit class changed")
    atomic_json(OUT / "build-receipt.json", build)
    return build


def main(count: int) -> None:
    existing = OUT / "build-receipt.json"
    if existing.exists():
        build = json.loads(existing.read_text())
        if (base.terminal_state_sha() != build["frozen_campaign_state_sha256"] or
                any(base.sha(CONTROL / "classes" / relative) != build[key] for relative, key in (
                    ("baseline/solr103940/FeedbackProbe.class", "timing_probe_class_sha256"),
                    ("org/apache/solr/common/cloud/SolrZkClient.class", "timing_zkclient_class_sha256"),
                    ("org/apache/solr/update/processor/RoutedAliasUpdateProcessor.class", "timing_route_class_sha256"),
                    ("org/apache/solr/update/processor/TimeRoutedAliasUpdateProcessorTest.class", "original_junit_class_sha256")))):
            raise RuntimeError("Timing-control build changed")
    else:
        build = prepare()
    frozen = build["frozen_campaign_state_sha256"]
    summary = OUT / "summary.json"
    rows = json.loads(summary.read_text())["runs"] if summary.exists() else []
    for number in range(len(rows) + 1, len(rows) + count + 1):
        if base.sha(STATE) != frozen or shutil.disk_usage(CASE).free < 10.5 * 1024 ** 3:
            raise RuntimeError("Frozen campaign changed or disk guard tripped")
        java_count = sum(line == "java" for line in subprocess.check_output(
            ["ps", "-eo", "comm="], text=True).splitlines())
        if java_count >= 5:
            raise RuntimeError(f"No JVM slot ({java_count} Java processes)")
        output = OUT / f"trial-{number:03d}"
        proc = subprocess.run([sys.executable, str(CONTROL / "probe/run.py"),
                               str(output), "--coverage", "--faults",
                               build["first_fault_selector"], "--timeout", "360"],
                              capture_output=True, text=True, check=False)
        trace = events(output / "events.tsv")
        manifest = json.loads((output / "manifest.json").read_text())
        faults = [e for e in trace if e["kind"] == "IO_APPLIED_CONNECTION_LOSS"]
        failures = [e for e in trace if e["kind"] == "IO_UNDERLYING_CONNECTION_LOSS"]
        successes = [e for e in trace if e["kind"] == "IO_UNDERLYING_RETRY_SUCCESS"]
        gates = [e for e in trace if e["kind"] == "TARGET_DELAY_GATE"]
        actor = runtime_actor(failures[0]) if failures else None
        target = [e for e in trace if e["kind"] == "TARGET_CHECK" and
                  len(e["parts"]) > 1 and e["parts"][1] == "SOLR-40" and
                  failures and e["seq"] > failures[0]["seq"] and
                  runtime_actor(e) == actor]
        throws = [e for e in trace if e["kind"] == "TARGET_EXCEPTION" and
                  e["parts"] and e["parts"][0] == "SOLR-40" and
                  failures and e["seq"] > failures[0]["seq"] and
                  runtime_actor(e) == actor]
        persisted, records = persisted_alias(output / "scratch")
        receipt = {
            "number": number, "model": build["model"],
            "frozen_campaign_state_sha256": frozen,
            "entry_fault_count": len(faults), "underlying_failure_count": len(failures),
            "retry_success_count": len(successes),
            "same_reader_entry_and_underlying": bool(faults and failures and
                runtime_actor(faults[0]) == actor),
            "target_identity_valid": checked_target_identity(trace),
            "same_reader_target_count": len(target),
            "same_reader_target_values": [e["parts"][0] for e in target],
            "same_reader_throw_count": len(throws),
            "delay_gates": [e["parts"] for e in gates],
            "target_after_retry_success": bool(successes and any(e["seq"] > successes[0]["seq"] for e in target)),
            "throw_after_retry_success": bool(successes and any(e["seq"] > successes[0]["seq"] for e in throws)),
            "persisted_alias_in_zk_txlog": persisted, "alias_txn_records": records,
            "junit_exit": manifest["exit_code"], "runner_exit": proc.returncode,
            "elapsed_seconds": manifest["elapsed_seconds"],
            "build_receipt_sha256": base.sha(OUT / "build-receipt.json"),
            "events_sha256": base.sha(output / "events.tsv"),
            "junit_log_sha256": base.sha(output / "junit.log"),
            "jacoco_sha256": base.sha(output / "jacoco.exec"),
        }
        atomic_json(output / "receipt.json", receipt)
        rows.append(receipt)
        atomic_json(summary, {"model": build["model"], "runs": rows})
        print(json.dumps({"trial": number, "underlying": len(failures),
                          "retry_success": len(successes), "delay_gate": len(gates),
                          "target_after_retry": receipt["target_after_retry_success"],
                          "same_reader_throw": len(throws), "junit_exit": manifest["exit_code"]}),
              flush=True)
        if base.sha(STATE) != frozen:
            raise RuntimeError("Frozen campaign changed during timing control")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.count <= 5:
        parser.error("count must be 1..5")
    main(args.count)
