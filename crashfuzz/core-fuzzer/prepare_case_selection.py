#!/usr/bin/env python3
"""Prepare the Soot I/O and coverage selection for one original checklist case."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from soot_selection import prepare

DEPENDENCIES = Path('/users/ZhenyuLi/.baseline-deps')
ROOT = Path('/users/ZhenyuLi/baseline')


def analysis_for(system: str) -> dict:
    if system.startswith('HDFS'):
        root = DEPENDENCIES / 'hadoop-3.4.3/share/hadoop'
        jars = [root / 'hdfs/hadoop-hdfs-3.4.3.jar',
                root / 'hdfs/hadoop-hdfs-client-3.4.3.jar',
                root / 'common/hadoop-common-3.4.3.jar']
        mappings = [ROOT / 'GraphChecker/experiments/hadoop/communication-mappings.jsonl']
    elif system.startswith('HBase'):
        root = DEPENDENCIES / 'hbase-2.6.6/lib'
        jars = [root / f'hbase-{module}-2.6.6.jar' for module in
                ('client', 'server', 'common', 'procedure', 'zookeeper',
                 'protocol', 'protocol-shaded', 'replication', 'master', 'regionserver')]
        jars = [jar for jar in jars if jar.is_file()]
        mappings = []
    elif system.startswith('Solr'):
        root = DEPENDENCIES / 'solr-8.11.4/dist'
        jars = [root / 'solr-core-8.11.4.jar', root / 'solr-solrj-8.11.4.jar']
        mappings = []
    elif system.startswith('ZooKeeper'):
        jars = [DEPENDENCIES / 'apache-zookeeper-3.8.7-bin/lib/zookeeper-3.8.7.jar']
        mappings = []
    else:
        raise ValueError(f'unknown system: {system}')
    if not jars or any(not jar.is_file() for jar in jars):
        raise FileNotFoundError(f'missing distribution jars for {system}: {jars}')
    return {'process_dirs': [str(jar) for jar in jars], 'classpath': [],
            'rpc_mapping_files': [str(path) for path in mappings],
            'max_methods': 400,
            'post_call_rpc_enabled': True}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--case-id', required=True)
    parser.add_argument('--checklist', type=Path,
                        default=ROOT / 'data/crashfuzz/checklist102.json')
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args()
    rows = json.loads(args.checklist.read_text())['rows']
    row = next((item for item in rows if item['case_id'] == args.case_id
                and item.get('selection_group') == 'original_102'), None)
    if row is None:
        raise ValueError(f'case not in original 102: {args.case_id}')
    target = row['exact_check_location']['site_id'].split('#', 1)[0]
    selection = prepare({'target': {'method': target}, 'static_selection':
                         {'analysis': analysis_for(row['system'])}},
                        args.output_root / args.case_id)
    location = row['exact_check_location']
    artifact = Path(selection['artifact_path'])
    selection['target_site_id'] = location['site_id']
    selection['target_check_line'] = location['check_start_line']
    selection['target_selected_line'] = location['selected_line']
    artifact.write_text(json.dumps(selection, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'case_id': args.case_id, 'system': row['system'],
                      'target_method': target, 'selection': selection['artifact_path'],
                      'coverage_methods': len(selection['coverage_methods']),
                      'io_calls': len(selection['io_calls']),
                      'branches': len(selection['branches'])}), flush=True)


if __name__ == '__main__':
    main()
