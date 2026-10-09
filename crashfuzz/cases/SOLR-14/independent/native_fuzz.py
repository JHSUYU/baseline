#!/usr/bin/env python3
"""Resume a separate coverage/I/O campaign at Solr's native ZK retry operation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import fuzz as engine
from build import HERE
from run import run as run_junit


NATIVE = HERE / 'native'
AGENT = NATIVE / 'solrsplit-native-agent.jar'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--max-trials', type=int, default=48)
    parser.add_argument('--max-faults', type=int, default=8)
    args = parser.parse_args()
    if not (1 <= args.max_trials <= 1000 and 1 <= args.max_faults <= 10):
        raise SystemExit('invalid budget')

    build = json.loads((NATIVE / 'build.json').read_text())
    if hashlib.sha256(AGENT.read_bytes()).hexdigest() != build['agent_sha256']:
        raise RuntimeError('native agent differs from frozen build')
    code = {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
            for name in ('fuzz.py', 'run.py', 'native_fuzz.py')}
    lock = NATIVE / 'fuzzer-lock.json'
    if lock.exists():
        if json.loads(lock.read_text()) != code:
            raise RuntimeError('native fuzzer code changed; refusing checkpoint resume')
    else:
        lock.write_text(json.dumps(code, indent=2, sort_keys=True) + '\n')
    engine.HERE = NATIVE
    engine.ROOT = NATIVE / 'campaign'
    engine.SEEDS = (NATIVE / 'healthy-01', NATIVE / 'healthy-02')
    engine.run_junit = lambda out, plan: run_junit(out, plan, agent_path=AGENT)

    # The original campaign and its checkpoint remain on the frozen v1 agent.
    # engine's runtime selection, mutation and per-trial JaCoCo feedback are
    # reused with an independent native seed, JAR digest, and checkpoint.
    engine.campaign(args.max_trials, args.max_faults)


if __name__ == '__main__':
    main()
