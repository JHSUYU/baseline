#!/usr/bin/env python3
"""Run the generic Solr JUnit driver with pinned v15 Solr 06 full campaign artifacts."""

import argparse
import os
from pathlib import Path

import solr_junit_runner_v15 as run_pilot


VERSIONED_AGENT = (run_pilot.MALLORY / "instrumentation/target"
                   / "mallory-agent-taskobserve-ordinal.jar")
VERSIONED_ADAPTER = run_pilot.HERE / "target/mallory-solr-adapter-v4.jar"
VERSIONED_INVENTORY = run_pilot.HERE / "releases/v15/inventory.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_id")
    parser.add_argument("--source", type=Path,
                        default=Path.home() / ".mallory-worktrees/solr")
    parser.add_argument("--distribution", type=Path,
                        default=Path.home() / ".baseline-deps/solr-8.11.4")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=420)
    parser.add_argument("--campaign", action="store_true")
    parser.add_argument("--compile-only", action="store_true")
    args = parser.parse_args()
    # Keep the campaign's agent and adapter paths explicit in the trial record.
    run_pilot.AGENT = VERSIONED_AGENT
    run_pilot.ADAPTER = VERSIONED_ADAPTER
    run_pilot.INVENTORY = VERSIONED_INVENTORY
    os.environ["MALLORY_SOLR_AGENT_JAR"] = str(VERSIONED_AGENT)
    os.environ["MALLORY_SOLR_ADAPTER_JAR"] = str(VERSIONED_ADAPTER)
    result = run_pilot.run(args.case_id, args.source, args.distribution,
                           args.output, args.timeout, args.campaign,
                           args.compile_only)
    print(__import__("json").dumps(result, sort_keys=True))
    return result.get("exit_code", 0)


if __name__ == "__main__":
    raise SystemExit(main())
