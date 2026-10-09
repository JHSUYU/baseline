#!/usr/bin/env python3
"""Review the reproducible SOLR-15 throw against original source and JUnit oracle."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from build import HERE, SOURCE
from fuzz import load_events


ROOT = HERE / 'supplemental/shardsplit'
CASE = 'SOLR/SPLIT/collection1/shard1/PARENT_LEADER'
COMMAND = SOURCE / 'solr/core/src/java/org/apache/solr/cloud/api/collections/SplitShardCmd.java'
TEST = SOURCE / 'solr/core/src/test/org/apache/solr/cloud/api/collections/ShardSplitTest.java'


def verify(name: str) -> dict:
    directory = ROOT / name
    run = json.loads((directory / 'run.json').read_text())
    audit = json.loads((directory / 'audit.json').read_text())
    assert audit['strict_injection'] and audit['applied_faults'] == 2
    assert audit['target_outcomes']['SOLR-15'] == {
        'post_fault_exact_throw': 1, 'post_fault_final_check': 1}
    assert audit['target_outcomes']['SOLR-16']['post_fault_exact_throw'] == 0
    assert audit['post_fault_outer_guard'] == 1
    assert run['exit_code'] == 0 and audit['junit'] == [1, 0, 0]
    events = load_events(directory)
    first = next(event for event in events if event['event'] == 'IO_RESULT'
                 and event['sourceKey'] == CASE and 'exists1' in event['siteId'])
    second = next(event for event in events if event['event'] == 'IO_RESULT'
                  and event['sourceKey'] == CASE and 'exists2' in event['siteId'])
    throw = next(event for event in events if event['event'] == 'TARGET_THROW'
                 and event['marker'] == 'TARGET:SOLR15:THROW'
                 and event['sourceKey'] == CASE)
    assert first['detail'].startswith('owner=') and second['detail'] == 'stat=null'
    assert first['physicalNode'] == second['physicalNode']
    assert second['seq'] < throw['seq']
    assert all(event['physicalNode'] == second['physicalNode']
               for event in audit['applied_events'])
    log = (directory / 'console.log').read_text()
    assert 'Shard split request state is failed' in log
    assert 'Update shard state shard1_0 to recovery_failed' in log
    assert 'Update shard state shard1_1 to recovery_failed' in log
    assert re.search(r'SOLR_SPLIT_ORIGINAL_JUNIT ran=1 ignored=0 failures=0', log)
    return {
        'run': name,
        'elapsed_seconds': run['elapsed_seconds'],
        'test_seed': run['test_seed'],
        'strict_applied_faults': 2,
        'first_live_node_result': first['detail'],
        'second_live_node_result': second['detail'],
        'physical_parent_leader': second['physicalNode'],
        'exact_target_throw': throw['detail'],
        'subshards_recovery_failed_logged': ['shard1_0', 'shard1_1'],
        'split_request_failed_logged': True,
        'original_junit': {'ran': 1, 'ignored': 0, 'failures': 0},
        'audit': str(directory / 'audit.json'),
    }


def main() -> None:
    source = COMMAND.read_text()
    test = TEST.read_text()
    assert 'if (leaderZnodeStat == null || ephemeralOwner != leaderZnodeStat.getEphemeralOwner())' in source
    assert 'Slice.State.RECOVERY_FAILED.toString()' in source
    assert 'the leader is not live anymore, fail the split!' in source
    assert "we don't care if the split failed because we are injecting faults" in test
    assert 'checkShardConsistency(true, true, addFails, deleteFails);' in test
    assert 'assertEquals("Found " + ctrlDocs + " control docs and " + cloudClientDocs' in test
    runs = [verify(name) for name in ('native-chaos-fault-02', 'native-chaos-replay-01')]
    assert runs[0]['physical_parent_leader'] != runs[1]['physical_parent_leader']
    review = {
        'case_id': 'SOLR-15',
        'original_source_revision': 'e27f44e3d78dfcec230c97e0a1240e3751daeff9',
        'command_source_sha256': hashlib.sha256(COMMAND.read_bytes()).hexdigest(),
        'test_source_sha256': hashlib.sha256(TEST.read_bytes()).hexdigest(),
        'source_path': 'solr/core/src/java/org/apache/solr/cloud/api/collections/SplitShardCmd.java',
        'source_guard_and_throw_lines': [524, 536, 538],
        'test_path': 'solr/core/src/test/org/apache/solr/cloud/api/collections/ShardSplitTest.java',
        'test_method': 'testSplitWithChaosMonkey',
        'source_behavior': ('Missing parent leader live znode causes both child shards '
                            'to be marked RECOVERY_FAILED and the split to abort.'),
        'original_test_oracle': ('The test explicitly permits split failure when its monkey '
                                 'stops the leader, then unconditionally verifies shard '
                                 'consistency and equal control/cloud document counts.'),
        'reproductions': runs,
        'classification': 'expected_protective_abort_not_new_bug',
        'bug_mark': 'none',
        'remaining_coverage_gap': ('SOLR-14 first live-node-null branch and SOLR-16 '
                                   'ephemeral-owner-change branch have not been exercised.'),
    }
    out = ROOT / 'solr15-native-candidate-source-review.json'
    out.write_text(json.dumps(review, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'classification': review['classification'],
                      'reproductions': len(runs),
                      'physical_leaders': [row['physical_parent_leader'] for row in runs]},
                     sort_keys=True))


if __name__ == '__main__':
    main()
