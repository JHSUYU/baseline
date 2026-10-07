#!/usr/bin/env python3
"""Check actor-specific I/O ordinals and fault application without a cluster."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent / "independent"
sys.path.insert(0, str(PARENT))
from build import JAVA8, original_classpath  # noqa: E402


def run_fixture(trace: Path, plan: Path | None = None,
                mode: str | None = None) -> str:
    cp = original_classpath() + ":" + str(HERE / "agent-classes")
    command = [str(JAVA8 / "java"), "-Xverify:all",
               "-Dsolrsubshard.fixture.identity=true",
               "-Dsolrsubshard.trace.file=" + str(trace)]
    if plan:
        command.append("-Dsolrsubshard.fault.plan=" + str(plan))
    command.extend(("-cp", cp, "org.apache.solr.research.solrsubshardv2.ActorFixture"))
    if mode:
        command.append(mode)
    return subprocess.check_output(command, text=True)


def io(trace: Path) -> list[dict]:
    return [event for event in (json.loads(line) for line in trace.read_text().splitlines())
            if event["event"] == "IO_OBSERVED"]


def main() -> None:
    cp = original_classpath() + ":" + str(HERE / "agent-classes")
    source = HERE / "src/research/solrsubshardv2/ActorFixture.java"
    subprocess.run([str(JAVA8 / "javac"), "-source", "8", "-target", "8",
                    "-cp", cp, "-d", str(HERE / "agent-classes"), str(source)],
                   check=True)
    healthy = HERE / "smoke-actor-healthy.jsonl"
    run_fixture(healthy)
    rows = io(healthy)
    if [row["actorKey"] for row in rows] != ["JETTY/shard2", "JETTY/shard1"]:
        raise AssertionError("unexpected actor bindings")
    if [row["hitOrdinal"] for row in rows] != [1, 1]:
        raise AssertionError("I/O ordinals were not partitioned by actor")
    plan = HERE / "smoke-actor-plan.properties"
    selected = rows[1]
    lines = ["count=1"]
    for field in ("marker", "siteId", "sourceKey", "actorKey", "resource", "hitOrdinal", "sessionGeneration"):
        lines.append(f"step.1.{field}={selected[field]}")
    plan.write_text("\n".join(lines) + "\n")
    faulted = HERE / "smoke-actor-faulted.jsonl"
    output = run_fixture(faulted, plan)
    rows = io(faulted)
    if [row["applied"] for row in rows] != [False, True]:
        raise AssertionError("wrong-actor I/O consumed fault step")
    if "ACTOR_V2_EXPECTED_CONNECTIONLOSS" not in output:
        raise AssertionError("planned actor did not receive the injected exception")
    wrong = HERE / "smoke-actor-wrong-session.jsonl"
    output = run_fixture(wrong, plan, "wrong-session")
    rows = io(wrong)
    if any(row["applied"] for row in rows) or "ACTOR_V2_EXPECTED_CONNECTIONLOSS" in output:
        raise AssertionError("reconnected session consumed generation-1 fault")
    if rows[-1]["sessionGeneration"] != 2 or rows[-1]["zkSessionId"] != 303:
        raise AssertionError("raw reconnect identity absent")
    target_trace = HERE / 'smoke-actor-wrong-target.jsonl'
    run_fixture(target_trace, mode='wrong-target')
    target = [event for event in (json.loads(line) for line in target_trace.read_text().splitlines())
              if event['event'] == 'TARGET_CHECK']
    if len(target) != 1 or target[0]['actorKey'] != 'UNBOUND:TARGET_CLIENT':
        raise AssertionError('target receiver actor was inferred from node name alone')
    print("ACTOR_V2_MATCH_SMOKE_OK: wrong I/O actor, ZK session, and target receiver fail closed")


if __name__ == "__main__":
    main()
