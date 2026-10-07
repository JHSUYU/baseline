#!/usr/bin/env python3
"""Calibrate stable parent-forward HTTP selectors in two unchanged JUnit runs."""

from __future__ import annotations

from collections import Counter
import hashlib
from itertools import combinations
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE.parent))
from fuzz import junit_gate, load_events, point_id  # noqa: E402


MARKERS = frozenset(('FAULT:HTTP:parentForwardAdd',
                     'FAULT:HTTP:parentForwardDeleteById'))
TARGET_PREFIX = 'SOLR/SUBSHARD/collection1/shard1_'
SENDER_PREFIX = 'SOLR/PARENT/collection1/shard1/'
MAX_ATTEMPTS = 8


def point(event: dict) -> dict:
    return {name: event[name] for name in
            ('marker', 'siteId', 'senderKey', 'sourceKey', 'resource',
             'hitOrdinal')}


def stable_pair(exact: list[set[str]]) -> tuple[int, int, set[str]] | None:
    for first, second in combinations(range(len(exact)), 2):
        common = exact[first] & exact[second]
        commands = {json.loads(item)['marker'] for item in common}
        families = {(json.loads(item)['marker'],
                     json.loads(item)['senderKey'],
                     json.loads(item)['sourceKey']) for item in common}
        if commands == MARKERS and len(families) >= 4:
            return first, second, common
    return None


def main() -> bool:
    attempts = []
    exact = []
    directories = [HERE / f'healthy-sender-{number:02d}'
                   for number in range(1, MAX_ATTEMPTS + 1)
                   if (HERE / f'healthy-sender-{number:02d}' / 'run.json').is_file()]
    for directory in directories:
        events = load_events(directory)
        metadata = json.loads((directory / 'run.json').read_text())
        gate = junit_gate((directory / 'console.log').read_text())
        sends = [event for event in events
                 if event['event'] == 'IO_OBSERVED'
                 and event['marker'] in MARKERS
                 and event['sourceKey'].startswith(TARGET_PREFIX)
                 and event.get('senderKey', '').startswith(SENDER_PREFIX)]
        guards_by_case = {
            case_id: [event for event in events
                      if event['event'] == 'TARGET_CHECK'
                      and event['marker'] == marker
                      and event['sourceKey'].startswith(TARGET_PREFIX)]
            for case_id, marker in (
                ('SOLR-36', 'SOLR36:ACTIVE_SUBSHARD_GUARD'),
                ('SOLR-37', 'SOLR37:CHILD_RANGE_SUBSET_GUARD'))}
        throws = [event for event in events
                  if event['event'] == 'TARGET_THROW'
                  and event['marker'] in ('SOLR36:ACTIVE_SUBSHARD_THROW',
                                          'SOLR37:CHILD_RANGE_THROW')]
        if (metadata['exit_code'] != 0 or gate != (1, 0, 0)
                or {event['marker'] for event in sends} != MARKERS
                or any(not guards for guards in guards_by_case.values())):
            raise RuntimeError(f'{directory}: original JUnit/HTTP/target gate failed')
        exact.append({point_id(point(event)) for event in sends})
        attempts.append({
            'run': directory.name,
            'elapsed_seconds': metadata['elapsed_seconds'],
            'junit_gate': gate,
            'source_revision': metadata['original_source_revision'],
            'agent_sha256': metadata['agent_sha256'],
            'trace_sha256': hashlib.sha256(
                (directory / 'events.jsonl').read_bytes()).hexdigest(),
            'parent_forward_http_sends': len(sends),
            'parent_forward_http_sends_by_command': dict(
                Counter(event['marker'] for event in sends)),
            'parent_sender_replicas': dict(Counter(
                event['senderKey'] for event in sends)),
            'parent_sender_to_child_pairs': dict(Counter(
                event['senderKey'] + ' -> ' + event['sourceKey']
                for event in sends)),
            'logical_targets': dict(Counter(event['sourceKey'] for event in sends)),
            'physical_urls_by_logical_target': {
                source: sorted({event['physicalNode'] for event in sends
                                if event['sourceKey'] == source})
                for source in {event['sourceKey'] for event in sends}},
            'exact_target_guards_by_case': {
                case_id: len(guards)
                for case_id, guards in guards_by_case.items()},
            'target_guard_operands_by_case': {
                case_id: dict(Counter(event['detail'] for event in guards))
                for case_id, guards in guards_by_case.items()},
            'exact_target_throws': len(throws),
            'max_send_ordinal_by_target': {
                source: max(event['hitOrdinal'] for event in sends
                            if event['sourceKey'] == source)
                for source in {event['sourceKey'] for event in sends}},
        })
    if len({run['source_revision'] for run in attempts}) != 1 or len({
            run['agent_sha256'] for run in attempts}) != 1:
        raise RuntimeError('healthy attempts used different source or agent builds')
    selected = stable_pair(exact)
    if selected is None:
        return False
    first, second, common = selected
    runs = [attempts[first], attempts[second]]
    report = {
        'test': 'org.apache.solr.cloud.api.collections.ShardSplitTest#test',
        'methodology': 'independent_asm_original_junit_parent_forward_http',
        'runs': runs,
        'all_healthy_attempts': attempts,
        'selected_runs': [run['run'] for run in runs],
        'selection_reason': ('earliest pair with both parent-forward commands, '
                             'four exact parent-replica/child command families, '
                             'and full selector overlap'),
        'stable_exact_http_selector_count': len(common),
        'stable_exact_http_selector_ids': sorted(common),
    }
    report['stable_exact_http_selectors_by_command'] = {
        marker: sum(json.loads(item)['marker'] == marker
                    for item in common)
        for marker in MARKERS}
    report['stable_exact_parent_child_command_families'] = dict(Counter(
        json.loads(item)['marker'] + ' | ' + json.loads(item)['senderKey']
        + ' -> ' + json.loads(item)['sourceKey']
        for item in common))
    selection = {
        'selected_runs': report['selected_runs'],
        'trace_sha256': [run['trace_sha256'] for run in runs],
        'agent_sha256': runs[0]['agent_sha256'],
        'source_revision': runs[0]['source_revision'],
        'excluded_runs': [run['run'] for index, run in enumerate(attempts)
                          if index not in (first, second)],
    }
    (HERE / 'seed-audit.json').write_text(json.dumps(report, indent=2,
                                                     sort_keys=True) + '\n')
    (HERE / 'seed-selection.json').write_text(json.dumps(selection, indent=2,
                                                        sort_keys=True) + '\n')
    print(json.dumps({key: value for key, value in report.items()
                      if key != 'stable_exact_http_selector_ids'}, sort_keys=True))
    return True


if __name__ == '__main__':
    main()
