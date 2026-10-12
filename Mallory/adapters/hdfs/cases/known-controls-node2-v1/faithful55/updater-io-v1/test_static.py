#!/usr/bin/env python3
"""No-JVM checks for the upstream fault boundary and conservative oracle."""
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit
import prepare


class Faithful55StaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generated = prepare.generate()

    def test_updater_fault_is_after_constructor_fetch(self):
        key = self.generated['original/org/apache/hadoop/hdfs/server/balancer/KeyManager.java']
        self.assertEqual(key.count('beforeUpdaterGetBlockKeys(KeyManager.this, namenode)'), 1)
        self.assertLess(key.index('final ExportedBlockKeys keys = namenode.getBlockKeys();'),
                        key.index('beforeUpdaterGetBlockKeys(KeyManager.this, namenode)'))
        self.assertIn('blockTokenSecretManager.addKeys(namenode.getBlockKeys());', key)

    def test_dn_guard_observes_actual_lookup_without_override(self):
        manager = self.generated[
            'main/org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager.java']
        selected = manager[manager.index('key = allKeys.get(keyId);'):]
        selected = selected[:selected.index('if (key == null) {')]
        self.assertIn('.observeAllKeys(this, blockPoolId, keyId, nonce, key != null);', selected)
        self.assertNotIn('key = null;', selected)
        self.assertNotIn('forceMissingAtAllKeys', manager)

    def test_fixed_foreground_fetch_stays_outside_updater_fault(self):
        fixed = self.generated['fixed/org/apache/hadoop/hdfs/server/balancer/KeyManager.java']
        method = fixed[fixed.index('public void updateBlockKeys() throws IOException'):]
        method = method[:method.index('@Override')]
        self.assertIn('ExportedBlockKeys fresh = namenode.getBlockKeys();', method)
        self.assertIn('foregroundKeysFetched(this, namenode, fresh);', method)
        self.assertNotIn('beforeUpdaterGetBlockKeys', method)

    def test_move_gate_precedes_socket_connection(self):
        for mode in ('original', 'fixed'):
            data = self.generated[
                f'{mode}/org/apache/hadoop/hdfs/server/balancer/Dispatcher.java']
            section = data[data.index('private void dispatch() {'):]
            self.assertLess(section.index('Hdfs55FaithfulProbe.beforeMove('),
                            section.index('sock.connect('))

    def test_bounded_outage_returns_to_real_updater_rpc(self):
        probe = (Path(__file__).resolve().parent / 'Hdfs55FaithfulProbe.java').read_text()
        runner = (Path(__file__).resolve().parent / 'run.py').read_text()
        test_source = self.generated[
            'test/org/apache/hadoop/hdfs/server/balancer/TestBalancerWithEncryptedTransfer.java']
        self.assertIn('Long.getLong("hdfs55f.maxOutageMs", 120000L)', probe)
        self.assertIn("'-Dhdfs55f.maxOutageMs=120000'", runner)
        self.assertIn('@Test(timeout=180000)', test_source)
        gate = probe[probe.index('public static synchronized void beforeUpdaterGetBlockKeys('):]
        gate = gate[:gate.index('public static synchronized void foregroundKeysFetched(')]
        self.assertIn('updaterFaults >= MAX_UPDATER_IO || elapsedMs >= MAX_OUTAGE_MS', gate)
        self.assertLess(gate.index('event("updater_outage_cap_reached'),
                        gate.index('++updaterFaults;'))
        self.assertIn('      return;\n    }\n    ++updaterFaults;', gate)

    def test_fresh_key_is_chosen_after_heartbeat_before_balancer(self):
        test = self.generated['test/org/apache/hadoop/hdfs/server/balancer/TestBalancer.java']
        section = test[test.index('private void runBalancer(Configuration conf, long totalDfsUsedSpace,') :]
        self.assertLess(section.index('waitForHeartBeat(totalDfsUsedSpace, totalCapacity, client, cluster);'),
                        section.index('Hdfs55FaithfulProbe.selectDestination('))
        self.assertLess(section.index('Hdfs55FaithfulProbe.selectDestination('),
                        section.index('final int run = runBalancer(namenodes, p, conf);'))

    def test_junit_failure_without_native_dn_lookup_is_no_proof(self):
        witness = audit.fault_witness(
            {'returncode': 1},
            'NO_MOVE_PROGRESS\nCONTROL original_junit_failures=1', [], fixed=False)
        self.assertFalse(witness['witness_passed'])
        self.assertIn('fresh_NN_key_manager_or_destination_missing', witness['gaps'])


if __name__ == '__main__':
    unittest.main()
