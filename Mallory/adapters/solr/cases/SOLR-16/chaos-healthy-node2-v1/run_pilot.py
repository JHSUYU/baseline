#!/usr/bin/env python3
"""Isolated direct-JUnit selector for the original SOLR-16 chaos workload."""

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOLR = HERE.parents[2]
sys.path.insert(0, str(SOLR))
import solr_junit_runner_v14 as runner  # noqa: E402

AGENT = (SOLR.parents[1] / "instrumentation/releases/b4bb6493699d87dceb966ff63b6f727455e5afdbbe1ddce4cd2247faab17eae4/mallory-agent.jar")
ADAPTER = SOLR / "target/mallory-solr-adapter-v38.jar"
SELECTOR = "org.apache.solr.cloud.api.collections.ShardSplitTest#testSplitWithChaosMonkey"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_id", choices=["SOLR-16"])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--distribution", type=Path,
                        default=Path.home() / ".baseline-deps/solr-8.11.4")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=420)
    parser.add_argument("--campaign", action="store_true")
    parser.add_argument("--compile-only", action="store_true")
    args = parser.parse_args()
    runner.INVENTORY = HERE / "inventory.json"
    runner.AGENT = AGENT
    runner.ADAPTER = ADAPTER
    if "#".join(runner.selected_test(args.case_id)[:2]) != SELECTOR:
        raise ValueError("isolated chaos JUnit selector changed")
    if os.environ.get("MALLORY_SOLR_NIGHTLY") != "1":
        raise ValueError("the unchanged @Nightly chaos JUnit requires MALLORY_SOLR_NIGHTLY=1")
    os.environ["MALLORY_SOLR_AGENT_JAR"] = str(AGENT)
    os.environ["MALLORY_SOLR_ADAPTER_JAR"] = str(ADAPTER)
    result = runner.run(args.case_id, args.source, args.distribution,
                        args.output, args.timeout, args.campaign,
                        args.compile_only)
    if result.get("test") != SELECTOR:
        raise ValueError("direct-JUnit runner executed a different selector")
    print(json.dumps(result, sort_keys=True))
    return result.get("exit_code", 0)


if __name__ == "__main__":
    raise SystemExit(main())
