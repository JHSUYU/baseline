#!/usr/bin/env python3
"""Strict no-JVM preflight for the separate SOLR-13 exploratory full run."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
HEALTHY = HERE.parent / 'source-healthy-node0-v1'
ORIGINAL = HERE.parent / 'source-admission-v1'
RELEASE = ROOT / 'Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f'
RAW = ROOT / 'data/mallory/solr13_source_healthy_node0_v1/healthy'
OUT = ROOT / 'data/mallory/campaigns/SOLR-13-source-exploratory-full-node0-v1'
CONFIG = HERE / 'config-full-node0.json'
GO = HERE / 'admission-full-node0.json'
DOOR = ('org.apache.solr.common.cloud.ZkStateReader$AliasesManager'
        '#applyModificationAndExportToZk(Ljava/util/function/UnaryOperator;)V@2259:door:1')
CHECK = ('org.apache.solr.cloud.api.collections.RoutedAlias'
         '#doSynchronous(Lorg/apache/solr/update/AddUpdateCommand;'
         'Lorg/apache/solr/cloud/api/collections/RoutedAlias$CandidateCollection;'
         'Lorg/apache/solr/core/CoreContainer;)'
         'Lorg/apache/solr/cloud/api/collections/RoutedAlias$CandidateCollection;@348:branch:1')


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def expected_config() -> dict:
    config = copy.deepcopy(read(HEALTHY / 'config-healthy-node0.json'))
    config['revision'] = 'SOLR-13-source-exploratory-full-node0-v1'
    config['admission'] = {
        'host': 'node0.baseline.silentfailure-pg0.utah.cloudlab.us',
        'lane': 'solr-node0-v1', 'source_lock':
            '/tmp/mallory-lanes/solr-source-graphchecker-8.11.4.lock',
        'output': str(OUT), 'scope': 'bounded_exploratory_full',
        'completion_rule': 'natural_terminal_budget_or_queue_exhaustion',
        'graph_path_role': 'outcome_evidence_not_launch_gate',
        'healthy_source_receipt': str(ROOT /
            'data/mallory/evidence_archives/SOLR-13-source-healthy-node0-v1.receipt.json'),
        'healthy_source_receipt_sha256':
            '2084a8b444e99842046a6bf59bc74b26cf2b1a11410435cf5cd3dab5e3b9e3cf',
        'healthy_exact_target_checks': 5,
        'healthy_typed_alias_write_doors': 19,
        'healthy_pretarget_typed_alias_write_doors': 15,
        'healthy_observed_event_time_paths': 0,
        'causal_path_status': 'unverified',
        'source_recovery': 'BadVersionException is caught at line 2262, aliases refresh and retry; one exception does not necessarily terminate the target request',
        'promotion_policy': 'core fresh healthy runtime attestation gates faults; candidate throws require independent source and replay review',
    }
    config['agent_properties']['auto.io.doors'] = False
    config['auto_promote_if_healthy'] = True
    config['budget'] = {'trials': 80, 'seconds': 3600,
                        'max_faults_per_trial': 3, 'trial_timeout_seconds': 480}
    config['calibration_only'] = False
    config['explore_outside_closure'] = True
    config['max_queue'] = 400
    config['single_fault_breadth_interval'] = 4
    config['require_event_time_paths'] = False
    config['mapping']['door_status'] = 'typed_BadVersion_retry_observed_healthy_graph_path_unverified'
    config['mapping']['healthy_seed_verified'] = True
    config['mapping']['node_identity_binding_verified'] = True
    config['mapping']['runner_status'] = 'pinned_v38_junit_runner_observed_healthy_fresh_full_pending'
    config['mapping']['status'] = 'source_admitted_exploratory_full_pending_runtime'
    config['mapping']['verified_healthy_probe'] = str(
        ROOT / 'data/mallory/evidence_archives/SOLR-13-source-healthy-node0-v1.receipt.json')
    config['runtime_artifacts'].extend([
        {'path': str(ROOT / 'data/mallory/evidence_archives/SOLR-13-source-healthy-node0-v1.receipt.json'),
         'sha256': '2084a8b444e99842046a6bf59bc74b26cf2b1a11410435cf5cd3dab5e3b9e3cf'},
        {'path': str(ROOT / 'data/mallory/evidence_archives/SOLR-13-source-healthy-node0-v1.members.json'),
         'sha256': 'b8d259b4b4f2579163f4e6eb1c64e97077bb30552c0c8ecae86fb556b3f304d7'},
        {'path': str(ROOT / 'data/mallory/evidence_archives/SOLR-13-source-healthy-node0-v1.tar.gz'),
         'sha256': 'f0086e9aea2db29daac19e2f59c4b6f26b6b8d33f756703484d093f3154fb367'},
        {'path': str(RAW / 'result.json'),
         'sha256': '887a7bf2f219ca4dbd04224bee0c79aa65a07a814204081a4169fbf5b2e79b94'},
        {'path': str(RAW / 'source-healthy-node0-gate.json'),
         'sha256': 'c845c9da238785cbcb02ae8f6dd4fbbc89d59cb4c0215c5d7bb19615f09080fa'},
    ])
    return config


def main() -> dict:
    subprocess.run([sys.executable, str(ORIGINAL / 'preflight.py')], check=True,
                   stdout=subprocess.DEVNULL)
    subprocess.run([sys.executable, str(HEALTHY / 'run_campaign.py'), '--mode',
                    'healthy', '--preflight-only'], check=True,
                   stdout=subprocess.DEVNULL)
    config = read(CONFIG)
    if config != expected_config():
        raise ValueError('full config differs from sealed healthy source and bounded policy')
    sys.path.insert(0, str(RELEASE))
    from Mallory.core import campaign  # noqa: E402
    if not Path(campaign.__file__).resolve().is_relative_to(RELEASE):
        raise ValueError('campaign core was not loaded from pinned release')
    campaign.validate_config(config)
    for artifact in config['runtime_artifacts']:
        path = Path(artifact['path'])
        if not path.is_file() or sha(path) != artifact['sha256']:
            raise ValueError(f'runtime artifact changed: {path}')
    receipt = read(ROOT / 'data/mallory/evidence_archives/SOLR-13-source-healthy-node0-v1.receipt.json')
    result = read(RAW / 'result.json')
    gate = read(RAW / 'source-healthy-node0-gate.json')
    trial = read(RAW / 'trials/r0000/result.json')
    if not (receipt.get('all_archive_members_verified') is True
            and receipt.get('archive_sha256') ==
                'f0086e9aea2db29daac19e2f59c4b6f26b6b8d33f756703484d093f3154fb367'
            and result.get('healthy_seed_valid') is True
            and result.get('runtime_attestation', {}).get('valid') is True
            and result.get('healthy_junit_validation', {}).get('status') == 'passed'
            and result.get('fault_trials_completed') == 0
            and trial.get('feedback', {}).get('target_region_present') is True
            and trial['feedback'].get('target_identity_complete') is True
            and gate.get('status') == 'passed'
            and gate.get('target_check_count') == 5
            and gate.get('typed_door_count') == 19
            and gate.get('observed_event_time_paths') == []
            and gate.get('full_campaign_admitted') is False):
        raise ValueError('sealed healthy target, actor, or door evidence changed')
    selected = [d for d in trial['feedback']['doors'] if d.get('site') == DOOR]
    if (len(selected) != 15 or any(d.get('in_closure') for d in selected)
            or config['target']['check_sites'] != [CHECK]
            or config['agent_properties']['auto.io.doors'] is not False
            or config['require_event_time_paths'] is not False
            or config['reject_coarse_roots'] is not True
            or config['allow_local_timeline_doors'] is not True):
        raise ValueError('exploratory door restriction or target closure changed')
    manifest = read(HERE / 'sha-manifest.json')
    if manifest.get('case_id') != 'SOLR-13':
        raise ValueError('wrong case-local manifest')
    for name, record in manifest['files'].items():
        path = HERE / name
        if (not path.is_file() or path.stat().st_size != record['bytes']
                or sha(path) != record['sha256']):
            raise ValueError(f'case-local file changed: {name}')
    request = read(HERE / 'admission-request.json')
    if not (request.get('go') is False
            and request.get('execution_status') == 'not_launched'
            and request.get('case_id') == 'SOLR-13'
            and request.get('host') == 'node0'
            and request.get('mode') == 'full'
            and request.get('config_sha256') == sha(CONFIG)
            and request.get('runner_sha256') == sha(HERE / 'run_campaign.py')
            and request.get('manifest_sha256') == sha(HERE / 'sha-manifest.json')
            and request.get('intended_output') == str(OUT)):
        raise ValueError('full admission request changed')
    source = Path(config['cwd'])
    if (subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'],
                                text=True).strip() !=
            config['mapping']['source_git_revision']
            or subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'],
                                       text=True).strip()):
        raise ValueError('Solr source revision or cleanliness changed')
    for name, relative in (
            ('target_source_sha256', 'solr/core/src/java/org/apache/solr/cloud/api/collections/RoutedAlias.java'),
            ('zk_state_reader_source_sha256', 'solr/solrj/src/java/org/apache/solr/common/cloud/ZkStateReader.java'),
            ('test_source_sha256', 'solr/core/src/test/org/apache/solr/update/processor/TimeRoutedAliasUpdateProcessorTest.java')):
        if sha(source / relative) != config['mapping'][name]:
            raise ValueError(f'Solr source SHA changed: {name}')
    for jar_key, jar_sha_key, clazz, clazz_sha_key in (
            ('compiled_jar', 'compiled_jar_sha256',
             'org/apache/solr/cloud/api/collections/RoutedAlias.class',
             'compiled_class_sha256'),
            ('aliases_manager_compiled_jar', 'aliases_manager_compiled_jar_sha256',
             'org/apache/solr/common/cloud/ZkStateReader$AliasesManager.class',
             'aliases_manager_class_sha256')):
        # The healthy config records the SolrJ class but not its JAR path.
        mapping = config['mapping']
        if jar_key == 'aliases_manager_compiled_jar':
            jar = Path('/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist/solr-solrj-8.11.4.jar')
            expected_jar_sha = 'b274e65f3607224b3337e9fc797137d8093c7981bcb54b695644dfd5d2242517'
        else:
            jar = Path(mapping[jar_key])
            expected_jar_sha = mapping[jar_sha_key]
        if sha(jar) != expected_jar_sha:
            raise ValueError(f'compiled JAR SHA changed: {jar}')
        with zipfile.ZipFile(jar) as archive:
            if hashlib.sha256(archive.read(clazz)).hexdigest() != mapping[clazz_sha_key]:
                raise ValueError(f'compiled class SHA changed: {clazz}')
    return {'status': 'strict_static_preflight_passed', 'case_id': 'SOLR-13',
            'mode': 'full', 'config_sha256': sha(CONFIG),
            'runner_sha256': sha(HERE / 'run_campaign.py'),
            'manifest_sha256': sha(HERE / 'sha-manifest.json'),
            'healthy_receipt_sha256': sha(ROOT /
                'data/mallory/evidence_archives/SOLR-13-source-healthy-node0-v1.receipt.json'),
            'intended_output': str(OUT), 'jvm_launched': False,
            'causal_path_status': 'unverified', 'go': False}


if __name__ == '__main__':
    print(json.dumps(main(), sort_keys=True))
