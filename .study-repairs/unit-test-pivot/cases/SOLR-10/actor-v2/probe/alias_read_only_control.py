#!/usr/bin/env python3
"""SOLR-40 isolated alias-read-only control with one genuine retry.

The original embedded-cluster JUnit and target processor remain byte-identical.
No F0 or method-entry plan fault is configured. One underlying ZooKeeper
getData('/aliases.json') fails on the real node1 AliasesManager reader.
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
STATE = CASE / "evidence/campaign-v4/state.json"
CONTROL = Path.home() / "solr40-alias-read-only-v12b"
OUT = CASE / "evidence/alias-read-only-v12b"


def prepare() -> dict:
    frozen = base.terminal_state_sha()
    base.CONTROL = CONTROL
    base.OUT = OUT
    build = base.prepare(frozen)
    java_source = CONTROL / "source" / earlier.ZKCLIENT
    content = java_source.read_text()
    content = earlier.replace_once(
        content,
        '        baseline.solr103940.FeedbackProbe.isFirstFaultApplied() &&\n',
        '')
    content = earlier.replace_once(
        content,
        'baseline.solr103940.FeedbackProbe.isPhysicalRole(this, "node1")',
        'baseline.solr103940.FeedbackProbe.isPhysicalRole(this, "node2")')
    java_source.write_text(content)
    cp = (CONTROL / "classpath.txt").read_text().strip()
    subprocess.run([earlier.JAVAC, "-cp", cp, "-d", str(CONTROL / "classes"),
                    str(java_source)], check=True)
    build.update({
        "model": "one underlying aliases.json watch read ConnectionLoss with no preceding plan fault; original retryOperation remains",
        "no_plan_fault": True,
        "selected_physical_reader": "jetty:node2",
        "healthy_seed_justification": "Both fresh V4 healthy traces show node2 alias watch read preceding a SOLR-40 target check on the same live client and manager; node1 has no such target in those traces",
        "alias_only_zkclient_source_sha256": base.sha(java_source),
        "alias_only_zkclient_class_sha256": base.sha(CONTROL / "classes" /
            "org/apache/solr/common/cloud/SolrZkClient.class"),
        "alias_only_probe_class_sha256": base.sha(CONTROL / "classes" /
            "baseline/solr103940/FeedbackProbe.class"),
        "alias_only_route_class_sha256": base.sha(CONTROL / "classes" /
            "org/apache/solr/update/processor/RoutedAliasUpdateProcessor.class"),
        "alias_only_junit_class_sha256": base.sha(CONTROL / "classes" /
            "org/apache/solr/update/processor/TimeRoutedAliasUpdateProcessorTest.class"),
    })
    if (build["alias_only_route_class_sha256"] != build["original_route_class_sha256"] or
            build["alias_only_junit_class_sha256"] != build["original_junit_class_sha256"]):
        raise RuntimeError("Original route or JUnit class changed")
    atomic_json(OUT / "build-receipt.json", build)
    return build


def main(count: int) -> None:
    existing = OUT / "build-receipt.json"
    if existing.exists():
        build = json.loads(existing.read_text())
        if base.terminal_state_sha() != build["frozen_campaign_state_sha256"]:
            raise RuntimeError("Frozen campaign checkpoint changed")
        for relative, key in (
            ("org/apache/solr/common/cloud/SolrZkClient.class", "alias_only_zkclient_class_sha256"),
            ("baseline/solr103940/FeedbackProbe.class", "alias_only_probe_class_sha256"),
            ("org/apache/solr/update/processor/RoutedAliasUpdateProcessor.class", "alias_only_route_class_sha256"),
            ("org/apache/solr/update/processor/TimeRoutedAliasUpdateProcessorTest.class", "alias_only_junit_class_sha256"),
        ):
            if base.sha(CONTROL / "classes" / relative) != build[key]:
                raise RuntimeError(f"Isolated class changed: {relative}")
    else:
        build = prepare()
    frozen = build["frozen_campaign_state_sha256"]
    summary_path = OUT / "summary.json"
    rows = json.loads(summary_path.read_text())["runs"] if summary_path.exists() else []
    for number in range(len(rows) + 1, len(rows) + count + 1):
        if base.sha(STATE) != frozen or shutil.disk_usage(CASE).free < 10.5 * 1024 ** 3:
            raise RuntimeError("Frozen state changed or disk guard tripped")
        java_count = sum(line == "java" for line in subprocess.check_output(
            ["ps", "-eo", "comm="], text=True).splitlines())
        if java_count >= 5:
            raise RuntimeError(f"No isolated JVM slot ({java_count} Java processes)")
        output = OUT / f"trial-{number:03d}"
        proc = subprocess.run([sys.executable, str(CONTROL / "probe/run.py"),
                               str(output), "--coverage", "--timeout", "360"],
                              capture_output=True, text=True, check=False)
        raw = events(output / "events.tsv")
        manifest = json.loads((output / "manifest.json").read_text())
        applied = [e for e in raw if e["kind"] == "IO_APPLIED_CONNECTION_LOSS"]
        faults = [e for e in raw if e["kind"] == "IO_UNDERLYING_CONNECTION_LOSS"]
        successes = [e for e in raw if e["kind"] == "IO_UNDERLYING_RETRY_SUCCESS"]
        actor = runtime_actor(faults[0]) if faults else None
        targets = [e for e in raw if e["kind"] == "TARGET_CHECK" and
                   len(e["parts"]) > 1 and e["parts"][1] == "SOLR-40" and
                   faults and e["seq"] > faults[0]["seq"] and
                   runtime_actor(e) == actor]
        throws = [e for e in raw if e["kind"] == "TARGET_EXCEPTION" and
                  e["parts"] and e["parts"][0] == "SOLR-40" and
                  faults and e["seq"] > faults[0]["seq"] and
                  runtime_actor(e) == actor]
        persisted, records = persisted_alias(output / "scratch")
        log = (output / "junit.log").read_text(errors="replace")
        receipt = {
            "number": number, "model": build["model"],
            "plan_fault_count": len(applied), "underlying_failure_count": len(faults),
            "underlying_actor": actor, "retry_success_count": len(successes),
            "same_reader_target_count": len(targets),
            "same_reader_target_values": [e["parts"][0] for e in targets],
            "same_reader_throw_count": len(throws),
            "same_reader_target_before_retry_success": bool(successes and
                any(e["seq"] < successes[0]["seq"] for e in targets)),
            "same_reader_target_after_retry_success": bool(successes and
                any(e["seq"] > successes[0]["seq"] for e in targets)),
            "target_identity_valid": checked_target_identity(raw),
            "alias_create_http_success": any("action=CREATEALIAS" in line and
                "status=0" in line for line in log.splitlines()),
            "exact_target_failure_in_junit": "Routed alias myalias appears to have been removed" in log,
            "persisted_alias_in_zk_txlog": persisted, "alias_txn_records": records,
            "junit_exit": manifest["exit_code"], "runner_exit": proc.returncode,
            "elapsed_seconds": manifest["elapsed_seconds"],
            "frozen_campaign_state_sha256": frozen,
            "build_receipt_sha256": base.sha(OUT / "build-receipt.json"),
            "original_test_class_sha256": manifest["original_test_class_sha256"],
            "events_sha256": base.sha(output / "events.tsv"),
            "junit_log_sha256": base.sha(output / "junit.log"),
            "jacoco_sha256": base.sha(output / "jacoco.exec"),
        }
        atomic_json(output / "receipt.json", receipt)
        rows.append(receipt)
        atomic_json(summary_path, {"model": build["model"], "runs": rows})
        print(json.dumps({"trial": number, "alias_fault": len(faults),
                          "plan_fault": len(applied), "retry_success": len(successes),
                          "same_reader_target": len(targets), "same_reader_throw": len(throws),
                          "junit_exit": manifest["exit_code"]}), flush=True)
        if base.sha(STATE) != frozen:
            raise RuntimeError("Frozen campaign changed during alias-only control")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.count <= 5:
        parser.error("count must be 1..5")
    main(args.count)
