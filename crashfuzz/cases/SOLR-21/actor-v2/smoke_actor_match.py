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


def run_fixture(trace: Path, plan: Path | None = None) -> str:
    cp = original_classpath() + ":" + str(HERE / "agent-classes")
    command = [str(JAVA8 / "java"), "-Dsolrreload.trace.file=" + str(trace)]
    if plan:
        command.append("-Dsolrreload.fault.plan=" + str(plan))
    command.extend(("-cp", cp, "org.apache.solr.research.solrreloadv2.ActorFixture"))
    return subprocess.check_output(command, text=True)


def io(trace: Path) -> list[dict]:
    return [event for event in (json.loads(line) for line in trace.read_text().splitlines())
            if event["event"] == "IO_OBSERVED"]


def main() -> None:
    cp = original_classpath() + ":" + str(HERE / "agent-classes")
    source = HERE / "src/research/solrreloadv2/ActorFixture.java"
    subprocess.run([str(JAVA8 / "javac"), "-source", "8", "-target", "8",
                    "-cp", cp, "-d", str(HERE / "agent-classes"), str(source)],
                   check=True)
    healthy = HERE / "smoke-actor-healthy.jsonl"
    run_fixture(healthy)
    rows = io(healthy)
    if [row["actorKey"] for row in rows] != ["UNBOUND:SOLR_HOME:node2", "JETTY/node1"]:
        raise AssertionError("unexpected actor bindings")
    if [row["hitOrdinal"] for row in rows] != [1, 1]:
        raise AssertionError("I/O ordinals were not partitioned by actor")
    plan = HERE / "smoke-actor-plan.properties"
    selected = rows[1]
    lines = ["count=1"]
    for field in ("marker", "siteId", "sourceKey", "actorKey", "resource", "hitOrdinal"):
        lines.append(f"step.1.{field}={selected[field]}")
    plan.write_text("\n".join(lines) + "\n")
    faulted = HERE / "smoke-actor-faulted.jsonl"
    output = run_fixture(faulted, plan)
    rows = io(faulted)
    if [row["applied"] for row in rows] != [False, True]:
        raise AssertionError("wrong-actor I/O consumed fault step")
    if "SOLR21_ACTOR_V2_EXPECTED_CONNECTIONLOSS" not in output:
        raise AssertionError("planned actor did not receive the injected exception")
    print("SOLR21_ACTOR_V2_MATCH_SMOKE_OK: node2 unbound, node1 faulted")


if __name__ == "__main__":
    main()
