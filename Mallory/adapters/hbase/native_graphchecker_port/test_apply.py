import unittest
from pathlib import Path

from apply import changed_sources


class NativeHBasePatchTest(unittest.TestCase):
    def test_original_runtime_and_wire_boundaries(self):
        source = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")
        if not source.exists():
            self.skipTest("original HBase 2.6.6 source unavailable")
        changed = changed_sources(source)
        by_name = {str(path.relative_to(source)): text
                   for path, text in changed.items()}
        self.assertEqual(29, len(by_name))
        self.assertFalse(any("edu.uva.liftlab.mallory.graphchecker.runtime"
                             in text for text in by_name.values()))
        client = by_name["hbase-client/src/main/java/org/apache/hadoop/hbase/ipc/NettyRpcConnection.java"]
        self.assertIn("GraphCheckerHBaseProtocol.requestWriteFailed(call);", client)
        sasl = by_name["hbase-client/src/main/java/org/apache/hadoop/hbase/security/NettyHBaseSaslRpcClientHandler.java"]
        self.assertIn("else frame.aborted();", sasl)
        bridge = by_name["hbase-client/src/main/java/org/apache/hadoop/hbase/ipc/GraphCheckerHBaseDoors.java"]
        self.assertIn("MessageDoors.outboundRequest(wireTransport(transport),", bridge)
        self.assertIn('correlation + "-" + attempt', bridge)
        self.assertIn("missingState || ambiguousReplay", bridge)
        self.assertIn('"SASL_REPLAY_KEY_COLLISION".equals(reason)', bridge)
        self.assertIn("MessageDoors.inbound(trace, symbolic, wireTransport(transport),", bridge)
        self.assertIn("MessageDoors.stored(wireTransport(transport), key, owner);", bridge)
        self.assertIn("transport.toUpperCase(Locale.ROOT)", bridge)
        meta = by_name["hbase-client/src/main/java/org/apache/hadoop/hbase/GraphCheckerHBaseMetaState.java"]
        self.assertIn("HBASE_META_STATE_READ_FROM_UNPROVEN", meta)
        protocol = by_name["hbase-client/src/main/java/org/apache/hadoop/hbase/ipc/GraphCheckerHBaseProtocol.java"]
        collision = protocol.index('if (collision > 1)')
        self.assertIn('return;', protocol[collision:collision + 400])
        sasl = by_name["hbase-client/src/main/java/org/apache/hadoop/hbase/ipc/GraphCheckerHBaseSaslProtocol.java"]
        collision = sasl.index('if (ordinal > 1)')
        self.assertIn('return;', sasl[collision:collision + 400])


if __name__ == "__main__":
    unittest.main()
