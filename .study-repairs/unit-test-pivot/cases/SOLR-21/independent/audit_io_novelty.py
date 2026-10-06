#!/usr/bin/env python3
"""Separate semantic ZooKeeper I/O novelty from ephemeral election znode names."""

from __future__ import annotations

import json
from pathlib import Path
import re

from build import HERE
from fuzz import family, load_events, point, relevant


ROOT = HERE / 'campaign'
ELECTION = re.compile(r'(/leader_elect/[^/]+/election/)[^/]+$')


def semantic(item: dict) -> str:
    return family(item)


def raw_family(item: dict) -> str:
    return '|'.join((item['marker'], item['siteId'], item['sourceKey'],
                     item['resource']))


def families(directory: Path) -> tuple[set[str], set[str], int]:
    items = [point(event) for event in load_events(directory)
             if event['event'] == 'IO_OBSERVED' and relevant(point(event))]
    return ({raw_family(item) for item in items},
            {semantic(item) for item in items},
            len({item['resource'] for item in items
                 if ELECTION.search(item['resource'])}))


def main() -> None:
    state = json.loads((ROOT / 'state.json').read_text())
    seed_pairs = [families(HERE / name) for name in ('healthy-04', 'healthy-05')]
    raw_seen = seed_pairs[0][0] | seed_pairs[1][0]
    semantic_seen = seed_pairs[0][1] | seed_pairs[1][1]
    seed_raw = len(raw_seen)
    seed_semantic = len(semantic_seen)
    rows = []
    for row in state['completed']:
        directory = Path(row['trace']).parent
        raw, sem, dynamic_paths = families(directory)
        valid = bool(row['strict_injection'] and row['target_preserved'])
        raw_gain = len(raw - raw_seen) if valid else 0
        semantic_gain = len(sem - semantic_seen) if valid else 0
        rows.append({
            'trial_number': row['trial_number'],
            'valid_strict_target_preserving': valid,
            'reported_raw_io_family_gain': row['new_io_families'],
            'recounted_raw_io_family_gain': raw_gain,
            'semantic_io_family_gain': semantic_gain,
            'dynamic_election_resource_names_observed': dynamic_paths,
            'production_probe_gain': row['new_production_probes'],
        })
        if valid:
            raw_seen |= raw
            semantic_seen |= sem
    result = {
        'methodology': 'exact_runtime_callsite_source_and_path_with_election_ephemeral_suffix_normalized_for_feedback_only',
        'identity_injection_unchanged': True,
        'healthy_raw_io_families': seed_raw,
        'healthy_semantic_io_families': seed_semantic,
        'valid_raw_io_family_gain': len(raw_seen) - seed_raw,
        'valid_semantic_io_family_gain': len(semantic_seen) - seed_semantic,
        'dynamic_election_name_artifact_gain': (len(raw_seen) - seed_raw)
                                               - (len(semantic_seen) - seed_semantic),
        'trials': rows,
    }
    output = ROOT / 'semantic-io-audit.json'
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'trials'},
                     sort_keys=True))


if __name__ == '__main__':
    main()
