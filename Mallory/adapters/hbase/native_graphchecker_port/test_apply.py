import hashlib
import json
import unittest
from pathlib import Path

from apply import changed_sources


HERE = Path(__file__).resolve().parent
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class NativeHBasePatchTest(unittest.TestCase):
    def test_frozen_hbase01_02_overlay_matches_pre_decoupling_output(self):
        if not SOURCE.exists():
            self.skipTest("original HBase 2.6.6 source unavailable")
        golden = json.loads((HERE / "native_output_golden.json").read_text())
        expected = {row["path"]: row for row in golden["rows"]}
        actual = {path.relative_to(SOURCE).as_posix(): output
                  for path, output in changed_sources(SOURCE).items()}
        self.assertEqual(set(expected), set(actual))
        for relative, row in expected.items():
            with self.subTest(relative=relative):
                source = SOURCE / relative
                self.assertEqual(row["source_sha256"],
                                 sha256(source.read_bytes()) if source.is_file() else None)
                self.assertEqual(row["output_sha256"],
                                 sha256(actual[relative].encode("utf-8")))

    def test_original_runtime_and_wire_boundaries(self):
        source = SOURCE
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
