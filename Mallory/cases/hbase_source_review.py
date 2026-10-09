#!/usr/bin/env python3
"""Record source review and separately label any terminal HBase seed evidence.

This deliberately does not change Mallory eligibility. A runtime healthy seed
must still resolve exact target and fault-door reach for every case.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
CALIBRATION = HERE.parents[1] / "data" / "mallory" / "calibration"
DETAILS = {
    "HBASE-01": ("normal_path_plausible", [1183, 1190],
        "The test creates an enabled table and explicitly calls relocateRegion; a normal meta lookup can evaluate the dead-server check without throwing."),
    "HBASE-02": ("normal_path_plausible", [1183, 1190],
        "Cleanup may disable an old table, but the test creates a fresh enabled table before relocateRegion; the disabled-table precondition should evaluate false."),
    "HBASE-04": ("normal_path_plausible", [139, 145, 213, 298, 320, 355, 403],
        "testMobStoreScanner delegates to several scanner helpers that call admin.flush on the created table; the enabled-table check can take its normal branch."),
    "HBASE-07": ("normal_path_plausible", [158, 159, 167, 168],
        "Both snapshot restores are preceded by disableTable; the restoreSnapshot disabled-table check can evaluate false."),
    "HBASE-08": ("normal_path_plausible", [143, 148, 153],
        "The test creates and reads a named namespace before table operations; getNamespace can return its descriptor. Its quota-failure stages concern other checks."),
    "HBASE-10": ("target_reach_uncertain", [105, 107, 109, 113],
        "The test unassigns a region and then tries a move, but it catches DoNotRetryRegionException rather than this check's HBaseIOException for a live procedure. Whether preTransitCheck sees a procedure still attached needs a healthy trace."),
    "HBASE-11": ("expected_target_exception", [105, 107, 109],
        "After explicitly unassigning a region, the test moves it and catches the selected DoNotRetryRegionException as the intended result."),
    "HBASE-12": ("expected_target_exception", [116, 120, 122],
        "The test disables the table, attempts a move, and catches the selected DoNotRetryIOException as the intended result."),
    "HBASE-13": ("normal_path_plausible", [167, 170, 188, 192],
        "The helper submits a merge of fresh table regions and asserts procedure success; no merge-parent qualifier is deliberately left behind."),
    "HBASE-14": ("normal_path_plausible", [167, 170, 188, 192],
        "The helper merges known table regions and asserts success; the unknown-region branch is not an intended outcome."),
    "HBASE-15": ("normal_path_plausible", [167, 170, 188, 192],
        "The helper merges online table regions and asserts success; the not-opened-region rejection is not intended."),
    "HBASE-16": ("internal_retry_exception_risk", [170, 176, 183, 185],
        "The test kills a region server and waits for three procedure timeout increases. The selected throw is documented in confirmClosed as a normal signal to retry with backoff when the region remains CLOSING; target throws must not automatically count as bugs."),
    "HBASE-17": ("assertion_requires_ea", [158, 175, 183, 193],
        "The selected check is a Java assert in confirmClosed. A direct-Java test JVM must enable assertions with -ea; the test's server-abort sequence may then reach this assertion, subject to runtime trace."),
    "HBASE-18": ("internal_retry_exception_risk", [73, 88, 95, 96],
        "The test injects an assignment failure and waits for the procedure. confirmOpened throws the selected HBaseIOException after too many immediate retries to back off; if observed, it may be expected internal recovery behavior."),
    "HBASE-19": ("expected_target_exception", [638, 645, 646],
        "The test attempts to add a column family while region reopening is disabled, then catches the selected HBaseIOException and checks its message."),
    "HBASE-20": ("expected_target_exception", [675, 681, 682],
        "The test attempts a coprocessor change while region reopening is disabled, then catches the selected HBaseIOException and checks its message."),
    "HBASE-21": ("expected_target_exception", [719, 728, 730, 733, 734],
        "The test lowers the namespace region quota before restoreSnapshot and explicitly expects a RestoreSnapshotException caused by the selected QuotaExceededException."),
    "HBASE-22": ("expected_target_exception", [141, 153, 159, 161, 162],
        "With one region already counted and a five-region maximum, the test tries to create a five-region table and expects the quota violation as an IOException."),
    "HBASE-23": ("normal_path_plausible", [154, 158, 159],
        "The selected test drives a normal single-member ZooKeeper-backed procedure through both startup orders; any completed-member payload should carry the protocol magic prefix."),
    "HBASE-24": ("normal_path_plausible", [115, 116],
        "runCommit drives a normal four-member procedure; the malformed-PB-prefix rejection is not an intended test outcome."),
    "HBASE-27": ("normal_path_plausible", [103, 104, 105, 106],
        "The test boots a region server before the master and waits for cluster startup. The wait loop can evaluate stopped=false while the server is waiting."),
    "HBASE-28": ("normal_path_plausible", [84, 88, 91, 93],
        "The test starts local info servers and fetches their pages; the configured bind address should pass isLocalAddress."),
    "HBASE-29": ("normal_path_plausible", [310, 311],
        "The test drives two-replica replication; replay requests built for one region should pass the same-region check if this RPC is reached."),
    "HBASE-30": ("normal_path_plausible", [310, 311],
        "The test drives two-replica replication; successful replay operation statuses should pass the selected status check if this RPC is reached."),
    "HBASE-31": ("target_reach_uncertain", [105, 107, 116, 120],
        "The test exercises offline and disabled-region move rejection. It does not intentionally send a close RPC with a stale server start code; exact throwOnWrongStartCode reach needs a trace."),
    "HBASE-32": ("healthy_guard_requires_error_path", [315, 328, 336],
        "The selected throw/check is inside RegionReplicaFlushHandler's catch(IOException) after a flush RPC. This test creates many replicas and performs reads but does not deliberately produce that IOException; a fault-free seed may never enter the target check."),
    "HBASE-33": ("healthy_guard_requires_error_path", [418, 419, 423, 425],
        "The test generates a token and immediately retrieves its password from the same secret manager. The selected watcher-aborted check is nested under a missing master-key lookup; neither a missing key nor watcher abort is arranged by this method."),
    "HBASE-34": ("normal_path_plausible", [128, 135, 138],
        "testOnlyToken delegates to testToken with ordinary credentials. The final masterKey-null guard can evaluate false after a valid key lookup; exact retrieval path needs runtime confirmation."),
    "HBASE-35": ("normal_path_plausible", [57, 73, 84, 91],
        "The test runs hbck on ordinary meta rows while testing orphan replication queues; the previous-entry check can evaluate null normally, without duplicate meta rows."),
    "HBASE-37": ("normal_path_plausible", [94, 99, 112, 117],
        "The test renders a region-server status page with an active master; master-address znode data should exist when getMasterInfoPort is called."),
}


def terminal_seed_evidence(case_id: str) -> dict | None:
    receipt = CALIBRATION / case_id / "result.json"
    if not receipt.is_file():
        return None
    result = json.loads(receipt.read_text())
    if result.get("status") == "running":
        return None
    trial = next((item for item in result.get("trials", [])
                  if item.get("trial_id") == 0), {})
    truncated = trial.get("status") == "trace_truncated"
    return {
        "grade": "real_jvm_terminal_healthy_seed",
        "receipt": str(receipt.relative_to(HERE.parents[1])),
        "campaign_status": result.get("status"),
        "duration_seconds": result.get("duration_seconds"),
        "target_reached": trial.get("target_reached"),
        "selected_target_exception_trials": result.get("exact_exception_trials"),
        "target_node_named": result.get("target_node_named"),
        "target_identity_gap_count": len(result.get("target_identity_gaps", [])),
        "trace_truncated": truncated,
        "eligible_doors_before_target": trial.get("eligible_doors_before_target"),
        "fault_trials_completed": result.get("fault_trials_completed", 0),
        "identity_interpretation": ("unassessed_after_trace_truncation" if truncated else
                                    "campaign_receipt_identity_gate"),
    }


def main() -> None:
    inventory = json.loads((HERE / "inventory.json").read_text())
    cases = [row for row in inventory["cases"] if row["system"] == "hbase"]
    assert len(cases) == len(DETAILS) == 30
    rows = []
    for case in cases:
        case_id = case["case_id"]
        state, lines, reason = DETAILS[case_id]
        workload = case["workload"]
        rows.append({"case_id": case_id, "review": state,
                     "selected_selector": workload["selected_selector"],
                     "test_source": workload["test_source_path"],
                     "test_evidence_lines": lines,
                     "target_source": case["target"]["source_path"],
                     "target_line": case["target"]["source_line"],
                     "target_function": case["target"]["function"],
                     "compiled_check_sites": (case["target"].get("runtime_mapping") or {}).get("check_sites"),
                     "target_exception": case["target"]["target_exception"],
                     "runtime_evidence": terminal_seed_evidence(case_id),
                     "reason": reason,
                     "next_step": ("Select a workload that reaches the same guard without intentionally throwing; calibrate exact bytecode site and named identity before fuzzing."
                                   if state == "expected_target_exception" else
                                   "Run a healthy target/site-catalog calibration and inspect the selected exception before any bug classification.")})
    result = {"schema_version": 1, "scope": "HBase 2.6.6 original 30 selected Mallory candidate workloads",
              "basis": "Source inference and separately labeled terminal JVM healthy-seed receipts; no eligibility or fault-result update",
              "source_root": "/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6",
              "source_commit": cases[0]["provenance"]["source_commit"],
              "review_counts": dict(Counter(row["review"] for row in rows)),
              "cases": rows}
    output = HERE / "hbase_test_mapping_recommendations.json"
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n")
    os.replace(temporary, output)
    print(output, result["review_counts"])


if __name__ == "__main__":
    main()
