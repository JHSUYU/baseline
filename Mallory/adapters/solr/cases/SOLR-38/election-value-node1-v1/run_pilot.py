#!/usr/bin/env python3
"""Pinned Solr v38 direct JUnit with this case's value adapter."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
sys.path.insert(0, str(ROOT / "Mallory/adapters/solr"))
import solr_junit_runner_v14 as runner  # noqa: E402

AGENT = ROOT / ("Mallory/instrumentation/releases/"
                "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9/"
                "mallory-agent.jar")
ADAPTER = HERE / "adapter/target/mallory-solr-adapter.jar"
INVENTORY = ROOT / "Mallory/adapters/solr/releases/v20/inventory.json"


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
    runner.AGENT = AGENT
    runner.ADAPTER = ADAPTER
    runner.INVENTORY = INVENTORY
    os.environ["MALLORY_SOLR_AGENT_JAR"] = str(AGENT)
    os.environ["MALLORY_SOLR_ADAPTER_JAR"] = str(ADAPTER)
    result = runner.run(args.case_id, args.source, args.distribution,
                        args.output, args.timeout, args.campaign,
                        args.compile_only)
    print(json.dumps(result, sort_keys=True))
    return result.get("exit_code", 0)


if __name__ == "__main__":
    raise SystemExit(main())
