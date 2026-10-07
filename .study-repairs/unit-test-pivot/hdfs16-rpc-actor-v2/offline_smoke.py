#!/usr/bin/env python3
"""Exercise actor-relative seed/queue logic without launching a cluster JVM."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile

from audit_campaign_v2 import inspect as inspect_campaign
from campaign_v2 import initialize, choose, finish, atom, sha
from run_v2 import TEST


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, str):
        path.write_text(value)
    else:
        path.write_text(json.dumps(value) + "\n")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="hdfs16-v2-smoke-") as directory:
        root = Path(directory)
        write(root / "healthy-calibration.json", {"pass": True, "case": "HDFS-16",
              "original_junit_seeds": 2, "legacy_trials_imported": 0,
              "seeds": [{"overlay_sha256": {"probe": "smoke"}},
                        {"overlay_sha256": {"probe": "smoke"}}],
              "shared_target_contexts": ['{"block_role":"original_test_file_block"}'],
              "shared_io_families": ["RPC_RESPONSE\tregisterDatanode\tdn0"]})
        for name, uuid, block, stamp in (("healthy-a", "uuid-a", 101, 1002),
                                          ("healthy-b", "uuid-b", 202, 2002)):
            rows = [
                {"seq": 1, "event": "IO_OBSERVED", "marker": "RPC_RESPONSE",
                 "api": "DatanodeProtocolClientSideTranslatorPB.registerDatanode",
                 "senderRole": "dn0", "senderActor": f"dn:{uuid}|bp:bp",
                 "peerPort": 19001, "ordinal": 1},
                {"seq": 2, "event": "TARGET_GUARD",
                 "site": "BlockInfo.setGenerationStampAndVerifyReplicas:428",
                 "caller": "BlockManager.updateLastBlock", "blockId": block,
                 "proposedGenerationStamp": stamp}]
            write(root / name / "runtime_trace.jsonl",
                  "".join(json.dumps(row) + "\n" for row in rows))
            write(root / name / "coverage.tsv",
                  "PROBE\tp1\nMETHOD\tm1\nBRANCH_UNIT\tb1\n")
        state = initialize(root, root / "campaign-v2/checkpoint.json")
        assert len(state["queue"]) == 3, state["queue"]
        assert all(item["target_context"] ==
                   {"caller": "BlockManager.updateLastBlock",
                    "block_role": "original_test_file_block"}
                   for item in state["queue"])
        assert all(item["sequence"][0]["senderRole"] == "dn0"
                   for item in state["queue"])
        assert all("uuid" not in json.dumps(item["sequence"]) for item in state["queue"])
        selected = choose(state)
        assert selected["sequence"][0]["ordinal"] == 1
        assert state["budget"]["effective"] == 80
        assert state["budget"]["attempt_cap"] == 320
        state["current"] = selected
        selected["run_id"] = "trial-0001-attempt-01"
        atom(root / "campaign-v2/checkpoint.json", state)
        run = root / selected["run_id"]
        step = selected["sequence"][0]
        plan = root / "campaign-v2/plans/trial-0001-attempt-01.tsv"
        write(plan, "\t".join(str(step[key]) for key in
              ("marker", "api", "senderRole", "ordinal", "exception")) + "\n")
        fault = {"threadId": 11, "marker": step["marker"], "api": step["api"],
                 "senderRole": "dn0", "senderActor": "dn:uuid-c|bp:bp",
                 "ordinal": 1, "peerPort": 19001}
        trace = [
            {"seq": 1, "event": "NN_ENDPOINT_REGISTER", "peerPort": 19001},
            {"seq": 2, "event": "DN_ROLE_REGISTER", "senderRole": "dn0", "dnUuid": "uuid-c"},
            {"seq": 3, "event": "DN_ROLE_REGISTER", "senderRole": "dn1", "dnUuid": "uuid-d"},
            {"seq": 4, "event": "DN_RPC_BIND", "threadId": 11,
             "senderActor": "dn:uuid-c|bp:bp", "senderRole": "dn0",
             "senderDnUuid": "uuid-c", "blockPoolId": "bp"},
            {"seq": 5, "event": "IO_OBSERVED", **fault},
            {"seq": 6, "event": "FAULT_MATCHED", **fault},
            {"seq": 7, "event": "FAULT_APPLIED", **fault,
             "exception": step["exception"]},
            {"seq": 8, "event": "TARGET_GUARD", "threadId": 12,
             "site": "BlockInfo.setGenerationStampAndVerifyReplicas:428",
             "caller": "BlockManager.updateLastBlock", "blockId": 303,
             "proposedGenerationStamp": 3002}]
        write(run / "runtime_trace.jsonl",
              "".join(json.dumps(row) + "\n" for row in trace))
        write(run / "jacoco.exec", "synthetic nonempty JaCoCo smoke artifact\n")
        write(run / "coverage.tsv", "PROBE\tp1\nMETHOD\tm1\nBRANCH_UNIT\tb1\n")
        write(run / "manifest.json", {"case_id": "HDFS-16", "test": TEST,
              "returncode": 0, "elapsed_seconds": 1.25,
              "plan_sha256": sha(plan),
              "trace_sha256": sha(run / "runtime_trace.jsonl"),
              "jacoco_sha256": sha(run / "jacoco.exec"),
              "coverage_sha256": sha(run / "coverage.tsv"),
              "overlay_sha256": {"probe": "smoke"}})
        row = finish(state, selected, root, root / "campaign-v2/checkpoint.json",
                     selected["run_id"])
        assert row["effective"] and row["target_context"]["block_role"] == \
            "original_test_file_block"
        result = inspect_campaign(root)
        assert result["pass"] and result["effective"] == 1, result["errors"]
    print("HDFS-16 cross-run role/context queue smoke PASS")


if __name__ == "__main__":
    main()
