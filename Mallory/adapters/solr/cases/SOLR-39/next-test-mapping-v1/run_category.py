#!/usr/bin/env python3
"""Run the pinned SOLR-39 Category JUnit through the existing v38 harness.

The selector inventory is local to this case.  The caller supplies the
controller's JAVA_TOOL_OPTIONS during a campaign run.
"""

import argparse
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
SOLR_ADAPTERS = HERE.parents[2]
sys.path.insert(0, str(SOLR_ADAPTERS))
import solr_junit_runner_v14 as runner  # noqa: E402

runner.INVENTORY = HERE / "inventory.json"
runner.AGENT = (SOLR_ADAPTERS.parent.parent / "instrumentation/releases/"
                "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9/"
                "mallory-agent.jar")
runner.ADAPTER = SOLR_ADAPTERS / "target/mallory-solr-adapter-v38.jar"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_id", choices=["SOLR-39"])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--distribution", type=Path,
                        default=Path.home() / ".baseline-deps/solr-8.11.4")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=420)
    parser.add_argument("--campaign", action="store_true")
    parser.add_argument("--compile-only", action="store_true")
    args = parser.parse_args()
    os.environ["MALLORY_SOLR_AGENT_JAR"] = str(runner.AGENT)
    os.environ["MALLORY_SOLR_ADAPTER_JAR"] = str(runner.ADAPTER)
    result = runner.run(args.case_id, args.source, args.distribution,
                        args.output, args.timeout, args.campaign,
                        args.compile_only)
    print(json.dumps(result, sort_keys=True))
    return result.get("exit_code", 0)


if __name__ == "__main__":
    raise SystemExit(main())
