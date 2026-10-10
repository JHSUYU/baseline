#!/usr/bin/env python3
"""Run the unchanged SOLR-38 cluster JUnit with the pinned value adapter."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

import config_v3

sys.path.insert(0, str(config_v3.ROOT / "Mallory/adapters/solr"))
import solr_junit_runner_v14 as runner  # noqa: E402

INVENTORY = config_v3.ROOT / "Mallory/adapters/solr/releases/v20/inventory.json"


def verify_campaign_context(output: Path, java_tool_options: str) -> None:
    properties = output / "agent.properties"
    if not properties.is_file():
        raise ValueError("controller agent properties missing")
    rows = {}
    for line in properties.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            rows[key] = value
    expected = f"-javaagent:{config_v3.AGENT}=config={properties}"
    actual = [part for part in shlex.split(java_tool_options)
              if part.startswith("-javaagent:")]
    if (actual != [expected]
            or rows.get("adapter.jar") != str(config_v3.ADAPTER)
            or rows.get("adapter.transformer") !=
               "edu.uva.liftlab.mallory.solr.SolrTransformer"
            or rows.get("events") != str(output / "events.jsonl")
            or not rows.get("run.id", "").startswith("SOLR-38-r")):
        raise ValueError("controller and direct JUnit agent/adapter identity differ")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_id", choices=("SOLR-38",))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--distribution", type=Path,
                        default=Path.home() / ".baseline-deps/solr-8.11.4")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=420)
    parser.add_argument("--campaign", action="store_true")
    parser.add_argument("--compile-only", action="store_true")
    args = parser.parse_args()
    runner.AGENT = config_v3.AGENT
    runner.ADAPTER = config_v3.ADAPTER
    runner.INVENTORY = INVENTORY
    os.environ["MALLORY_SOLR_AGENT_JAR"] = str(config_v3.AGENT)
    os.environ["MALLORY_SOLR_ADAPTER_JAR"] = str(config_v3.ADAPTER)
    if args.campaign:
        verify_campaign_context(args.output.resolve(), os.environ.get("JAVA_TOOL_OPTIONS", ""))
    result = runner.run(args.case_id, args.source, args.distribution,
                        args.output, args.timeout, args.campaign, args.compile_only)
    print(json.dumps(result, sort_keys=True))
    return result.get("exit_code", 0)


if __name__ == "__main__":
    raise SystemExit(main())
