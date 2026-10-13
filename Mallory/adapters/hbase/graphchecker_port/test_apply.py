import tempfile
import unittest
from pathlib import Path

import apply


SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")


class HBasePortPatchTest(unittest.TestCase):
    def test_exact_266_anchors_and_success_boundaries(self):
        if not SOURCE.is_dir():
            self.skipTest("HBase 2.6.6 source checkout unavailable")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative, replacements in apply.patches().items():
                source = (SOURCE / relative).read_text(encoding="utf-8")
                for before, after in replacements:
                    source = apply.edit(source, before, after, relative)
                output = root / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(source, encoding="utf-8")
            client = (root / "hbase-client/src/main/java/org/apache/hadoop/hbase/ipc"
                      / "NettyRpcConnection.java").read_text()
            netty = (root / "hbase-server/src/main/java/org/apache/hadoop/hbase/ipc"
                     / "NettyServerRpcConnection.java").read_text()
            simple = (root / "hbase-server/src/main/java/org/apache/hadoop/hbase/ipc"
                      / "SimpleRpcServerResponder.java").read_text()
            cluster = (root / "hbase-server/src/main/java/org/apache/hadoop/hbase/util"
                       / "JVMClusterUtil.java").read_text()
            connection = (root / "hbase-client/src/main/java/org/apache/hadoop/hbase/client"
                          / "ConnectionImplementation.java").read_text()
            callback = (root / "hbase-client/src/main/java/org/apache/hadoop/hbase/ipc"
                        / "BlockingRpcCallback.java").read_text()
            rpc_server = (SOURCE / "hbase-server/src/main/java/org/apache/hadoop/hbase/ipc"
                          / "RpcServer.java").read_text()
            self.assertIn("if (future.isSuccess()) {\n"
                          "        GraphCheckerHBaseProtocol.responseSent(resp);", netty)
            self.assertIn("if (!buf.hasRemaining()) {\n"
                          "      GraphCheckerHBaseProtocol.responseSent(resp);", simple)
            self.assertIn("GraphCheckerHBaseProtocol.requestSent(call);", client)
            self.assertIn('enterMiniClusterActor(regionServer, "REGION_SERVER")', cluster)
            self.assertIn('enterMiniClusterActor(master, "MASTER")', cluster)
            self.assertIn("new GraphCheckerContextThreadPoolExecutor(", connection)
            self.assertIn('MessageDoors.stored("hbase-blocking-rpc-callback",', callback)
            self.assertIn('MessageDoors.fetched("hbase-blocking-rpc-callback",', callback)
            self.assertNotIn("GraphCheckerHBaseProtocol.responseSent", rpc_server)
            self.assertIn("optional bytes mallory_graph_context = 4;",
                          (root / "hbase-protocol-shaded/src/main/protobuf/RPC.proto").read_text())


if __name__ == "__main__":
    unittest.main()
