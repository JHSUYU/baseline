#!/usr/bin/env python3
"""Summarize HDFS-33 map and actor events from one existing healthy trial."""

import argparse
import gzip
import json
from pathlib import Path

TARGET = 'org.apache.hadoop.hdfs.server.datanode.DataStorage$VolumeBuilder#build()V@259:'
MAP_PUT = 'org.apache.hadoop.hdfs.server.datanode.DataStorage#getBlockPoolSliceStorage('
MAP_READ = 'org.apache.hadoop.hdfs.server.datanode.DataStorage$VolumeBuilder#build()V@258:map:'
REMOVE = 'org.apache.hadoop.hdfs.server.datanode.DataStorage#removeBlockPoolStorage('
DIAGNOSTIC_DOORS = ('org.apache.hadoop.hdfs.server.datanode.StorageLocation#makeBlockPoolDir(',
                    'org.apache.hadoop.hdfs.server.datanode.BPServiceActor#offerService()V@703:door:')


def audit(trial):
    result = json.loads((trial / 'result.json').read_text())
    feedback = result.get('feedback', {})
    junit = result.get('junit_validation')
    receipt = trial / 'junit-receipt.json'
    if junit is None and receipt.exists():
        junit = json.loads(receipt.read_text())
    junit_ok = bool(junit and junit.get('status') == 'passed' and
                    (junit.get('tests'), junit.get('failures'), junit.get('errors')) == (1, 0, 0))
    with gzip.open(trial / 'events.jsonl.gz', 'rt') as source:
        events = [json.loads(line) for line in source]
    targets = [e for e in events if e.get('type') == 'TARGET_CHECK'
               and e.get('site', '').startswith(TARGET)]
    puts = [e for e in events if e.get('type') == 'STATE_WRITE'
            and e.get('site', '').startswith(MAP_PUT)]
    reads = [e for e in events if e.get('type') == 'STATE_READ'
             and e.get('site', '').startswith(MAP_READ)]
    removals = [e for e in events if e.get('type') == 'METHOD'
                and e.get('site', '').startswith(REMOVE)]
    doors = [e for e in events if e.get('type') == 'DOOR_OBSERVED'
             and e.get('site', '').startswith(DIAGNOSTIC_DOORS)]
    named = [e for e in targets if e.get('node') not in (None, '', 'unknown')]
    map_pairs = [
        {'put_seq': put['seq'], 'read_seq': read['seq'], 'key': read.get('key'),
         'object': read.get('object'), 'node': read.get('node')}
        for read in reads for put in puts
        if put['seq'] < read['seq'] and
        (put.get('object'), put.get('key')) == (read.get('object'), read.get('key')) and
        put.get('node') == read.get('node')
    ]
    target_seq = min((e['seq'] for e in targets), default=None)
    return {
        'case_id': 'HDFS-33', 'trial': str(trial),
        'target_checks': len(targets), 'named_target_checks': len(named),
        'target_nodes': sorted({str(e.get('node')) for e in targets}),
        'target_threw': bool(feedback.get('target_threw')),
        'junit_1_0_0': junit_ok,
        'map_puts': len(puts), 'target_map_reads': len(reads),
        'same_map_key_pre_target_pairs': [p for p in map_pairs
                                          if target_seq is not None and p['read_seq'] < target_seq],
        'remove_method_events': len(removals),
        'remove_method_events_before_target': sum(
            event['seq'] < target_seq for event in removals) if target_seq is not None else 0,
        'diagnostic_doors_before_target': [e.get('site') for e in doors
            if target_seq is not None and e['seq'] < target_seq],
        'named_healthy_target_observed': junit_ok and bool(named) and
                                         not feedback.get('target_threw'),
        'fault_campaign_admitted': False,
        'missing_edge': 'No observed typed I/O exception that removes the same block-pool map entry after prepareVolume and still reaches build; method entry alone cannot establish key-specific removal.'
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('trial_dir', type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.trial_dir), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
