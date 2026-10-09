#!/usr/bin/env python3
"""Read-only admission check for the isolated HBASE-12 client-bound seed."""

import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZipFile

ROOT = Path('/users/ZhenyuLi/baseline')
OVERLAY = ROOT / 'Mallory/adapters/hbase/overlays/request-qualified-rpc-hbase12-v1'
CONFIG = OVERLAY / 'cases/HBASE-12.client-scoped-healthy.json'
OUTPUT = ROOT / 'data/mallory/calibration_hbase12_client_scoped_v2/HBASE-12'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    config = json.loads(CONFIG.read_text())
    release = ROOT / 'Mallory/dispatch/releases' / config['core_release']['release_id']
    assert sha(release / 'manifest.json') == config['core_release']['manifest_sha256']
    sys.path.insert(0, str(release))
    from Mallory.core.campaign import validate_config
    validate_config(config)
    assert config['case_id'] == 'HBASE-12' and config['calibration_only']
    assert config['budget']['trials'] == 1
    assert config['mapping']['fault_admission_blocked']
    assert config['require_event_time_paths'] and not config['allow_local_timeline_doors']
    assert config['mapping']['request_qualified_rpc_port'] == (
        'hbase.pb.MasterService.UnassignRegion')
    assert config['mapping']['request_qualified_node'] == 'master0'
    assert config['command'][8:] == [
        'edu.uva.liftlab.mallory.hbase.pilot.SelectedJUnit',
        'org.apache.hadoop.hbase.client.TestAdmin2',
        'testShouldUnassignTheRegion']
    assert config['command'][5] == '-Dmallory.hbase.rpc.door.case=HBASE-12'
    assert config['command'][7].split(':')[0] == (
        config['mapping']['client_bound_runner_jar'])
    assert config['agent_properties']['adapter.transformers'].endswith(
        'hbase12.RequestQualifiedRpcTransformer')
    assert not OUTPUT.exists()
    for artifact in config['runtime_artifacts']:
        assert sha(artifact['path']) == artifact['sha256'], artifact['path']
    manifest = json.loads(Path(config['mapping']['client_bound_runner_manifest']).read_text())
    assert sha(config['mapping']['client_bound_runner_manifest']) == (
        config['mapping']['client_bound_runner_manifest_sha256'])
    assert manifest['runner_fqcn'] == config['command'][8]
    assert manifest['runner_jar_sha256'] == (
        config['mapping']['client_bound_runner_jar_sha256'])
    source = OVERLAY / 'src/client-bound-v1/edu/uva/liftlab/mallory/hbase/pilot/SelectedJUnit.java'
    assert sha(source) == manifest['source_sha256'] == (
        config['mapping']['client_bound_runner_source_sha256'])
    with ZipFile(config['mapping']['client_bound_runner_jar']) as archive:
        assert hashlib.sha256(archive.read(
            'edu/uva/liftlab/mallory/hbase/pilot/SelectedJUnit.class')).hexdigest() == (
                manifest['runner_class_sha256'])
    receipt = Path(config['mapping']['prior_scoped_healthy_receipt'])
    assert sha(receipt) == config['mapping']['prior_scoped_healthy_receipt_sha256']
    assert json.loads(receipt.read_text())['observed_path_doors'] == 1
    site = json.loads(Path(config['site_file']).read_text())
    assert site['doors'] == []
    assert [target['line'] for target in site['targets']] == [762, 763]
    for tree in (Path(config['mapping']['source_root']),
                 Path(config['source_equivalent_root'])):
        assert sha(tree / 'hbase-server/src/test/java/org/apache/hadoop/hbase/client/'
                   'TestAdmin2.java') == config['mapping']['test_source_sha256']
        assert sha(tree / config['target']['source_path']) == (
            config['mapping']['target_source_sha256'])
    print(json.dumps({'status': 'HBASE-12_client_scoped_healthy_preflight_passed',
                      'config_sha256': sha(CONFIG),
                      'runner_jar_sha256': sha(config['mapping']['client_bound_runner_jar']),
                      'runtime_artifact_count': len(config['runtime_artifacts']),
                      'output_absent': True,
                      'healthy_run_performed': False}, sort_keys=True))


if __name__ == '__main__':
    main()
