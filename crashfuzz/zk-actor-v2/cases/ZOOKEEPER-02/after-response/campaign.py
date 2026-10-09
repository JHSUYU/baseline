#!/usr/bin/env python3
"""Resumable ZK02 stage two on completed server sync responses.

The original pre-I/O checkpoint is a distinct namespace and never loaded here.
Only exact post-response sync I/O events may enter the queue. JUnit ConnectionLoss is
recorded separately from the selected owner-mismatch exception oracle.
"""

import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
sys.path.insert(0, str(CASE))
sys.path.insert(0, str(HERE))

import audit_calibration
from run_pilot import AGENT, ROOT, calibration, execute

# Importing a same-named module from this script is unsafe when invoked as a
# script; load the original by absolute path into an independent module name.
spec = importlib.util.spec_from_file_location('zk02_original_campaign', CASE / 'campaign.py')
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)

audit_calibration.ROOT = ROOT
engine.ROOT = ROOT
engine.AGENT = AGENT
engine.CHECKPOINT = ROOT / 'after-response-campaign.json'
engine.LEDGER = ROOT / 'after-response-trials.jsonl'
engine.LOCK = ROOT / 'after-response-campaign.lock'
engine.audit_seed = audit_calibration.one
engine.MAX_ATTEMPTS = 480
engine.INITIAL_BUDGET = 60  # 20 distinct client post-write trials are already complete.
engine.EXTENDED_BUDGET = 108  # Aggregate conditional extension is 128.

old_candidates = engine.candidates
RESPONSE_SITE = ('org.apache.zookeeper.server.NIOServerCnxn#handleWrite:299:'
                 'packetSent()V')


def candidates(rows, after=0):
    # In the original QuorumTest loop, the third response for each moved
    # connection acknowledges async sync(). The first is the handshake; the
    # second acknowledges synchronous setData and aborts the workload if
    # faulted. Two healthy runs and pilot-02 establish this exact ordinal.
    return [item for item in old_candidates(rows, after)
            if item['selector'].startswith(RESPONSE_SITE + '@@peer:')
            and item['selector'].endswith('@@3')
            and item['relation'] == 'same_session']


def run(run_id, plan, worker_id, worker_count=16, timeout=180):
    if worker_count != 16 or timeout != 180:
        raise ValueError('unexpected ZooKeeper worker settings')
    return execute(run_id, plan, calibration.sha(AGENT), worker_id)


engine.candidates = candidates
engine.run = run

if __name__ == '__main__':
    engine.main()
