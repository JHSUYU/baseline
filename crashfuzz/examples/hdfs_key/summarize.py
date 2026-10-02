"""Summarize exact key-check observations and matched fault trials."""

import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

from adhoc_crashfuzz.graph import build_graph, read_events, target_closure  # noqa: E402
from adhoc_crashfuzz.model import TargetSpec  # noqa: E402


TARGET = "org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager#retrieveDataEncryptionKey(I[B)[B#B1"
THROW = "org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager#retrieveDataEncryptionKey(I[B)[B#L555"


def main():
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else HERE / "out_fuzz"
    rows = []
    for path in sorted((root / "runs").glob("*/result.json")):
        run_dir = path.parent
        result = json.loads(path.read_text())
        events = read_events(run_dir / "traces")
        graph = build_graph(events)
        closure = target_closure(graph, TargetSpec(TARGET))
        guard = [event for event in events
                 if event.kind == "BRANCH" and event.site == TARGET]
        thrown = [event for event in events
                  if event.kind == "THROW" and event.site == THROW]
        message_kinds = {}
        for edge in closure.edges:
            if edge.kind == "MESSAGE":
                kind = edge.detail.split(":", 1)[0]
                message_kinds[kind] = message_kinds.get(kind, 0) + 1
        faults = [event["action"] for event in result["injected"]]
        rows.append({
            "run_id": result["run_id"],
            "planned_faults": len(result["sequence"]["actions"]),
            "matched_faults": len(faults),
            "injection_modes": [event.get("match_mode", "exact")
                                for event in result["injected"]],
            "fault_actions": faults,
            "target_reached": result["target_reached"],
            "target_fatal": result["target_fatal"],
            "key_present_branch": sum(event.outcome == "true" for event in guard),
            "key_missing_branch": sum(event.outcome == "false" for event in guard),
            "exact_invalid_key_throws": len(thrown),
            "closure_nodes": len(closure.nodes),
            "closure_edges": len(closure.edges),
            "closure_message_edges": message_kinds,
            "closure_state_candidate_edges": sum(
                edge.kind == "STATE_CANDIDATE" for edge in closure.edges),
            "graph_gaps": len(graph.gaps),
            "workload_returncode": result["workload"]["returncode"],
            "checker_returncode": (None if result["checker"] is None else
                                   result["checker"]["returncode"]),
        })
    fault_rows = [row for row in rows if row["run_id"].startswith("run-")]
    totals = {
        "completed_runs": len(rows),
        "fault_trials": len(fault_rows),
        "matched_fault_trials": sum(row["matched_faults"] > 0
                                    for row in fault_rows),
        "matched_fault_actions": sum(row["matched_faults"]
                                     for row in fault_rows),
        "matched_communication_boundary_actions": sum(
            action["trigger"]["site"].startswith(
                "org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferServer#receive")
            for row in fault_rows for action in row["fault_actions"]),
        "exact_guard_evaluations": sum(row["key_present_branch"] +
                                       row["key_missing_branch"]
                                       for row in rows),
        "fault_trials_reaching_exact_guard": sum(row["target_reached"]
                                                  for row in fault_rows),
        "fault_trials_with_missing_key_branch": sum(
            row["key_missing_branch"] > 0 for row in fault_rows),
        "fault_trials_with_exact_throw": sum(
            row["exact_invalid_key_throws"] > 0 for row in fault_rows),
        "fault_trials_with_workload_failure": sum(
            row["workload_returncode"] != 0 for row in fault_rows),
    }
    summary = {"target_guard": TARGET, "target_throw": THROW,
               "totals": totals, "runs": rows}
    (root / "report.json").write_text(json.dumps(summary, indent=2) + "\n")
    lines = ["# HDFS encryption-key check campaign", "",
             "The target is the exact compiled branch after `allKeys.get(keyId)`. "
             "A missing-key branch and a source-line throw are reported "
             "separately from method reachability and matched injection.", "",
             "Totals: " + ", ".join("{}={}".format(key, value)
                                    for key, value in totals.items()), "",
             "| Run | Matched/planned | Guard present/missing | Exact throw | Closure RPC/data-transfer edges | Workload/checker |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for row in rows:
        message_count = sum(row["closure_message_edges"].values())
        lines.append("| {} | {}/{} | {}/{} | {} | {} | {}/{} |".format(
            row["run_id"], row["matched_faults"], row["planned_faults"],
            row["key_present_branch"], row["key_missing_branch"],
            row["exact_invalid_key_throws"], message_count,
            row["workload_returncode"], row["checker_returncode"]))
    (root / "report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(totals, sort_keys=True))


if __name__ == "__main__":
    main()
