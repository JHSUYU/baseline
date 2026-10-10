#!/usr/bin/env python3
"""Require a named heartbeat door on the exact target's observed closure."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DOOR = ("org.apache.hadoop.hdfs.server.datanode.BPServiceActor#"
        "sendHeartBeat(Z)Lorg/apache/hadoop/hdfs/server/protocol/HeartbeatResponse;"
        "@563:door:1")
TARGET = "hdfs-cluster-1/nn0"


def review(trial: dict) -> dict:
    feedback = trial.get("feedback", {})
    junit = trial.get("junit_validation", {})
    targets = feedback.get("target_instances", [])
    doors = feedback.get("doors", [])
    matching = [door for door in doors
                if door.get("site") == DOOR
                and door.get("point", {}).get("node") == "hdfs-cluster-1/dn0"
                and door.get("in_closure") is True]
    valid = (trial.get("return_code") == 0
             and not trial.get("timed_out")
             and junit.get("tests") == 1
             and junit.get("errors") == 0
             and junit.get("failures") == 0
             and feedback.get("target_reached") is True
             and feedback.get("target_threw") is False
             and feedback.get("target_identity_complete") is True
             and not feedback.get("trace_truncated")
             and any(target.get("node") == TARGET for target in targets)
             and bool(matching))
    return {"case_id": "HDFS-18", "full_gate": "GO" if valid else "HOLD",
            "named_typed_closure_doors": len(matching),
            "named_target_instances": sum(t.get("node") == TARGET for t in targets),
            "junit_tests": junit.get("tests"), "target_threw": feedback.get("target_threw")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("trial_result", type=Path)
    args = parser.parse_args()
    print(json.dumps(review(json.loads(args.trial_result.read_text())), sort_keys=True))


if __name__ == "__main__":
    main()
