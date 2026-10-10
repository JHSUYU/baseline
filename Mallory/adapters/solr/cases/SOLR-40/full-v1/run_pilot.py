#!/usr/bin/env python3
"""Direct Solr JUnit entry point preserving the campaign's pinned agent."""

import argparse
import json
import os
import sys
from pathlib import Path

SOLR_ADAPTER = Path('/users/ZhenyuLi/baseline/Mallory/adapters/solr')
sys.path.insert(0, str(SOLR_ADAPTER))
import solr_junit_runner_v14 as runner  # noqa: E402

AGENT = Path('/users/ZhenyuLi/baseline/Mallory/adapters/solr/cases/SOLR-13/runtime-role-v1/releases/v1/mallory-agent.jar')
ADAPTER = SOLR_ADAPTER / 'target/mallory-solr-adapter-v38.jar'
INVENTORY = SOLR_ADAPTER / 'releases/v20/inventory.json'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case_id')
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--distribution', type=Path,
                        default=Path.home() / '.baseline-deps/solr-8.11.4')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=420)
    parser.add_argument('--campaign', action='store_true')
    parser.add_argument('--compile-only', action='store_true')
    args = parser.parse_args()
    runner.AGENT = AGENT
    runner.ADAPTER = ADAPTER
    runner.INVENTORY = INVENTORY
    os.environ['MALLORY_SOLR_AGENT_JAR'] = str(AGENT)
    os.environ['MALLORY_SOLR_ADAPTER_JAR'] = str(ADAPTER)
    result = runner.run(args.case_id, args.source, args.distribution,
                        args.output, args.timeout, args.campaign,
                        args.compile_only)
    print(json.dumps(result, sort_keys=True))
    return result.get('exit_code', 0)


if __name__ == '__main__':
    raise SystemExit(main())
