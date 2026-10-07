#!/usr/bin/env python3
"""Resumable ZK02 campaign restricted to verified complete client request writes.

The original pre-I/O checkpoint is a distinct namespace and never loaded here.
Only exact post-write I/O events may enter the queue. JUnit ConnectionLoss is
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
engine.CHECKPOINT = ROOT / 'afterio-campaign.json'
engine.LEDGER = ROOT / 'afterio-trials.jsonl'
engine.LOCK = ROOT / 'afterio-campaign.lock'
engine.audit_seed = audit_calibration.one
engine.MAX_ATTEMPTS = 480

old_candidates = engine.candidates
WRITE_SITE = ('org.apache.zookeeper.ClientCnxnSocketNIO#doIO:119:'
              'java.nio.channels.SocketChannel#write(Ljava/nio/ByteBuffer;)I')


def candidates(rows, after=0):
    return [item for item in old_candidates(rows, after)
            if item['selector'].startswith(WRITE_SITE + '@@client:handle:')
            and item['relation'] == 'same_session']


def run(run_id, plan, worker_id, worker_count=16, timeout=180):
    if worker_count != 16 or timeout != 180:
        raise ValueError('unexpected ZooKeeper worker settings')
    return execute(run_id, plan, calibration.sha(AGENT), worker_id)


engine.candidates = candidates
engine.run = run

if __name__ == '__main__':
    engine.main()
