#!/usr/bin/env python3
"""Generate the faithful HDFS-55 source overlay from exact Hadoop 3.4.3 anchors.

The --static mode performs all patch and invariant checks without Java or writes.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = Path('/users/ZhenyuLi/baseline')
SOURCE = Path('/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3')
HDFS = SOURCE / 'hadoop-hdfs-project/hadoop-hdfs/src'
MAIN = HDFS / 'main/java/org/apache/hadoop/hdfs'
TEST = HDFS / 'test/java/org/apache/hadoop/hdfs'
CRASH = BASE / 'crashfuzz/known-bug-controls/HDFS-17899'
PIN = HERE / 'source-pins.json'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def replace_once(data: str, old: str, new: str, label: str) -> str:
    if data.count(old) != 1:
        raise RuntimeError(f'{label}: expected one exact released source anchor, found {data.count(old)}')
    return data.replace(old, new, 1)


def control_patches():
    spec = importlib.util.spec_from_file_location('hdfs55_fix', CRASH / 'build_overlay.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def key_manager(data: str, fixed: bool, controls) -> str:
    if fixed:
        data = controls.patch_key_manager(data)
        data = replace_once(data, 'Hdfs17899Probe.markKeyCleared();',
                            'Hdfs55FaithfulProbe.markKeyCleared();', 'fixed clear observation')
        data = replace_once(data,
            '      blockTokenSecretManager.addKeys(namenode.getBlockKeys());\n'
            '    }\n  }\n\n  @Override\n  public void close()',
            '      ExportedBlockKeys fresh = namenode.getBlockKeys();\n'
            '      Hdfs55FaithfulProbe.foregroundKeysFetched(this, namenode, fresh);\n'
            '      blockTokenSecretManager.addKeys(fresh);\n'
            '    }\n  }\n\n  @Override\n  public void close()',
            'fixed foreground NN key refetch')
    data = replace_once(data,
        '      this.blockTokenSecretManager.addKeys(keys);',
        '      this.blockTokenSecretManager.addKeys(keys);\n'
        '      Hdfs55FaithfulProbe.managerConstructed(this, namenode, blockpoolID, keys);',
        'constructor after successful NN fetch')
    data = replace_once(data,
        '            blockTokenSecretManager.addKeys(namenode.getBlockKeys());',
        '            Hdfs55FaithfulProbe.beforeUpdaterGetBlockKeys(KeyManager.this, namenode);\n'
        '            blockTokenSecretManager.addKeys(namenode.getBlockKeys());',
        'updater typed IOException door')
    data = replace_once(data,
        '        if (encryptionKey == null ||\n'
        '            encryptionKey.expiryDate < timer.now()) {',
        '        boolean needsRefresh = encryptionKey == null ||\n'
        '            encryptionKey.expiryDate < timer.now();\n'
        '        Hdfs55FaithfulProbe.observeKeyCheck(this, encryptionKey, needsRefresh);\n'
        '        if (needsRefresh) {',
        'KeyManager cached-key guard')
    data = replace_once(data, '        return encryptionKey;',
        '        Hdfs55FaithfulProbe.observeKeyDecision(this, encryptionKey, needsRefresh);\n'
        '        return encryptionKey;', 'KeyManager decision')
    return data


def dispatcher(data: str, fixed: bool, controls) -> str:
    if fixed:
        data = controls.patch_dispatcher(data)
    start = data.index('    private void dispatch() {')
    end = data.index('    /** Send a reportedBlock replace request', start)
    section = data[start:end]
    anchor = '        sock.connect('
    replacement = ('        Hdfs55FaithfulProbe.beforeMove(\n'
                   '            target.getDatanodeInfo().getDatanodeUuid(),\n'
                   '            target.getDatanodeInfo().getXferAddr());\n'
                   '        sock.connect(')
    if fixed:
        anchor = '            sock.connect('
        replacement = ('            Hdfs55FaithfulProbe.beforeMove(\n'
                       '                target.getDatanodeInfo().getDatanodeUuid(),\n'
                       '                target.getDatanodeInfo().getXferAddr());\n'
                       '            sock.connect(')
    section = replace_once(section, anchor, replacement, 'PendingMove pre-connect gate')
    return data[:start] + section + data[end:]


def token_manager(data: str) -> str:
    data = replace_once(data,
        '    allKeys.put(nextKey.getKeyId(), nextKey);\n'
        '    return true;',
        '    allKeys.put(nextKey.getKeyId(), nextKey);\n'
        '    org.apache.hadoop.hdfs.server.balancer.Hdfs55FaithfulProbe\n'
        '        .nnRotation(this, currentKey, nextKey, allKeys.keySet());\n'
        '    return true;',
        'NN rotation after natural map update')
    data = replace_once(data,
        '        this.allKeys.put(receivedKeys[i].getKeyId(), receivedKeys[i]);\n'
        '      }\n'
        '    }\n'
        '  }\n\n'
        '  /**\n   * Update block keys',
        '        this.allKeys.put(receivedKeys[i].getKeyId(), receivedKeys[i]);\n'
        '      }\n'
        '    }\n'
        '    org.apache.hadoop.hdfs.server.balancer.Hdfs55FaithfulProbe\n'
        '        .dnMapAfterAdd(this, blockPoolId, allKeys.keySet());\n'
        '  }\n\n'
        '  /**\n   * Update block keys',
        'worker map after real addKeys')
    data = replace_once(data,
        '      key = allKeys.get(keyId);\n'
        '      if (key == null) {',
        '      key = allKeys.get(keyId);\n'
        '      org.apache.hadoop.hdfs.server.balancer.Hdfs55FaithfulProbe\n'
        '          .observeAllKeys(this, blockPoolId, keyId, nonce, key != null);\n'
        '      if (key == null) {',
        'native DN allKeys guard')
    if 'forceMissingAtAllKeys' in data or 'key = null;' in data[data.index('key = allKeys.get(keyId);'):data.index('if (key == null)', data.index('key = allKeys.get(keyId);'))]:
        raise RuntimeError('faithful DN lookup cannot override map result')
    return data


def bpos(data: str) -> str:
    start = data.index('  private boolean processCommandFromActive(')
    end = data.index('  private boolean processCommandFromStandby(', start)
    section = data[start:end]
    old = ('        dn.blockPoolTokenSecretManager.addKeys(\n'
           '            getBlockPoolId(), \n'
           '            ((KeyUpdateCommand) cmd).getExportedKeys());')
    new = old + ('\n        org.apache.hadoop.hdfs.server.balancer.Hdfs55FaithfulProbe\n'
                 '            .dnKeysApplied(dn.getDatanodeId().getDatanodeUuid(),\n'
                 '                dn.getXferAddress().toString(), getBlockPoolId(),\n'
                 '                dn.blockPoolTokenSecretManager.get(getBlockPoolId()),\n'
                 '                ((KeyUpdateCommand) cmd).getExportedKeys());')
    section = replace_once(section, old, new, 'DN active NN command after addKeys')
    return data[:start] + section + data[end:]


def server(data: str) -> str:
    peer = ('    if (peer.hasSecureChannel() ||\n'
            '        dnConf.getTrustedChannelResolver().isTrusted(getPeerAddress(peer))) {')
    if data.count(peer) != 2:
        raise RuntimeError('DN server peer anchor changed')
    data = data.replace(peer,
        '    org.apache.hadoop.hdfs.server.balancer.Hdfs55FaithfulProbe\n'
        '        .enterDnPeer(peer.getLocalAddressString());\n' + peer, 1)
    return replace_once(data,
        '        sendInvalidKeySaslErrorMessage(out, ioe.getCause().getMessage());',
        '        org.apache.hadoop.hdfs.server.balancer.Hdfs55FaithfulProbe\n'
        '            .markDnInvalidKeyResponse(ioe.getCause().getMessage());\n'
        '        sendInvalidKeySaslErrorMessage(out, ioe.getCause().getMessage());',
        'native DN INVALID_KEY wire response')


def test_balancer(data: str) -> str:
    data = replace_once(data,
        '      cluster.waitClusterUp();\n'
        '      cluster.waitActive();\n'
        '      client = NameNodeProxies.createProxy(conf,',
        '      cluster.waitClusterUp();\n'
        '      cluster.waitActive();\n'
        '      Hdfs55FaithfulProbe.configure(cluster.getNamesystem()\n'
        '          .getBlockManager().getBlockTokenSecretManager());\n'
        '      client = NameNodeProxies.createProxy(conf,',
        'MiniDFSCluster NN post-start key interval')
    data = replace_once(data,
        '      // run balancer and validate results\n'
        '      BalancerParameters.Builder pBuilder =',
        '      // Choose a fresh post-start NN key already installed on the new DN.\n'
        '      org.apache.hadoop.hdfs.server.datanode.DataNode targetDn =\n'
        '          cluster.getDataNodes().get(cluster.getDataNodes().size() - 1);\n'
        '      Hdfs55FaithfulProbe.selectDestination(\n'
        '          targetDn.getDatanodeId().getDatanodeUuid(),\n'
        '          targetDn.getXferAddress().toString());\n'
        '      // run balancer and validate results\n'
        '      BalancerParameters.Builder pBuilder =',
        'one-node destination and fresh-key gate')
    return data


def sasl_patcher(data: str) -> str:
    data = replace_once(data, 'public final class PatchSaslClient',
                        'public final class PatchFaithfulSaslClient', 'ASM class')
    data = replace_once(data, 'Hdfs17899Probe', 'Hdfs55FaithfulProbe', 'ASM hook owner')
    return data


SOURCES = {
    'KeyManager.java': MAIN / 'server/balancer/KeyManager.java',
    'Dispatcher.java': MAIN / 'server/balancer/Dispatcher.java',
    'BlockTokenSecretManager.java': MAIN / 'security/token/block/BlockTokenSecretManager.java',
    'BPOfferService.java': MAIN / 'server/datanode/BPOfferService.java',
    'SaslDataTransferServer.java': MAIN / 'protocol/datatransfer/sasl/SaslDataTransferServer.java',
    'TestBalancer.java': TEST / 'server/balancer/TestBalancer.java',
    'TestBalancerWithEncryptedTransfer.java': HERE.parents[1] / 'adapted55/TestBalancerWithEncryptedTransfer.java',
    'PatchSaslClient.java': CRASH / 'PatchSaslClient.java',
}


def generate() -> dict[str, str]:
    pins = json.loads(PIN.read_text())
    for name, path in SOURCES.items():
        if sha(path.read_bytes()) != pins['source_sha256'][name]:
            raise RuntimeError(f'source SHA changed: {path}')
    if sha((HERE / 'Hdfs55FaithfulProbe.java').read_bytes()) != pins['probe_sha256']:
        raise RuntimeError('probe SHA changed')
    controls = control_patches()
    source = {name: path.read_text() for name, path in SOURCES.items()}
    generated = {
        'main/org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager.java':
            token_manager(source['BlockTokenSecretManager.java']),
        'main/org/apache/hadoop/hdfs/server/datanode/BPOfferService.java':
            bpos(source['BPOfferService.java']),
        'main/org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferServer.java':
            server(source['SaslDataTransferServer.java']),
        'test/org/apache/hadoop/hdfs/server/balancer/TestBalancer.java':
            test_balancer(source['TestBalancer.java']),
        'test/org/apache/hadoop/hdfs/server/balancer/TestBalancerWithEncryptedTransfer.java':
            source['TestBalancerWithEncryptedTransfer.java'],
        'asm/PatchFaithfulSaslClient.java': sasl_patcher(source['PatchSaslClient.java']),
    }
    for mode in ('original', 'fixed'):
        generated[f'{mode}/org/apache/hadoop/hdfs/server/balancer/KeyManager.java'] = key_manager(
            source['KeyManager.java'], mode == 'fixed', controls)
        generated[f'{mode}/org/apache/hadoop/hdfs/server/balancer/Dispatcher.java'] = dispatcher(
            source['Dispatcher.java'], mode == 'fixed', controls)
    return generated


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--static', action='store_true')
    group.add_argument('--emit', type=Path)
    args = parser.parse_args()
    generated = generate()
    if args.emit:
        if args.emit.exists():
            raise RuntimeError(f'generated source directory exists: {args.emit}')
        for relative, body in generated.items():
            output = args.emit / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(body)
    print(json.dumps({'status': 'source_patch_static_pass',
                      'runtime_unverified': True,
                      'generated_sha256': {name: sha(body.encode()) for name, body in sorted(generated.items())},
                      'probe_sha256': sha((HERE / 'Hdfs55FaithfulProbe.java').read_bytes())},
                     sort_keys=True))


if __name__ == '__main__':
    main()
