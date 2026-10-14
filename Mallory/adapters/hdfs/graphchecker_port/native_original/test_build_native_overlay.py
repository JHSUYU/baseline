import hashlib
import unittest

from build_native_overlay import source_bridge


class NativeBridgeSourceTest(unittest.TestCase):
    def test_transport_handoff_remains_two_phase(self):
        source = source_bridge()
        self.assertEqual(
            "5a91fc62f25c32d0871492eb42ba50ce3970cd7d6756ab9ed950deefae6fa3ed",
            hashlib.sha256(source.encode("utf-8")).hexdigest(),
        )
        self.assertIn("NativeHdfsDoors.prepareOutbound", source)
        self.assertIn("NativeHdfsDoors.sent(transfer.outbound)", source)
        self.assertIn("REQUESTS.put(key(correlation, attempt), transfer);", source)
        self.assertIn("RESPONSES.put(key, transfer);", source)
        self.assertIn('server, scope, field(rawCall, "rv"));', source)
        self.assertNotIn("if (outbound.active()) REQUESTS.put", source)
        self.assertNotIn("if (outbound.active()) RESPONSES.put", source)
        self.assertNotIn("edu.uva.liftlab.mallory.graphchecker.runtime", source)


if __name__ == "__main__":
    unittest.main()
