#!/usr/bin/env python3
"""Run the original SOLR-40 JUnit with the case-local alias watcher probe."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
ADAPTER_DIR = ROOT / "Mallory/adapters/solr"
sys.path.insert(0, str(ADAPTER_DIR))
import solr_junit_runner_v14 as runner  # noqa: E402

AGENT = HERE.parent / "full-reference-handoff-node0-v2/releases/mallory-agent.jar"
ADAPTER = ADAPTER_DIR / "target/mallory-solr-adapter-v38.jar"
INVENTORY = ADAPTER_DIR / "releases/v20/inventory.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_id")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--distribution", type=Path,
                        default=Path.home() / ".baseline-deps/solr-8.11.4")
    parser.add_argument("--timeout", type=int, default=420)
    parser.add_argument("--campaign", action="store_true")
    args = parser.parse_args()
    if args.case_id != "SOLR-40":
        parser.error("only SOLR-40 is supported")
    runner.AGENT, runner.ADAPTER, runner.INVENTORY = AGENT, ADAPTER, INVENTORY
    os.environ["MALLORY_SOLR_AGENT_JAR"] = str(AGENT)
    os.environ["MALLORY_SOLR_ADAPTER_JAR"] = str(ADAPTER)
    result = runner.run(args.case_id, args.source, args.distribution,
                        args.output, args.timeout, args.campaign)
    print(json.dumps(result, sort_keys=True))
    return result.get("exit_code", 0)


if __name__ == "__main__":
    raise SystemExit(main())
