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
            sasl_client = (root / "hbase-client/src/main/java/org/apache/hadoop/hbase/security"
                           / "NettyHBaseSaslRpcClientHandler.java").read_text()
            sasl_server = (root / "hbase-server/src/main/java/org/apache/hadoop/hbase/ipc"
                           / "NettyHBaseSaslRpcServerHandler.java").read_text()
            meta = (root / "hbase-client/src/main/java/org/apache/hadoop/hbase"
                    / "MetaTableAccessor.java").read_text()
            async_meta = (root / "hbase-client/src/main/java/org/apache/hadoop/hbase"
                          / "AsyncMetaTableAccessor.java").read_text()
            procedure = (root / "hbase-procedure/src/main/java/org/apache/hadoop/hbase/procedure2"
                         / "ProcedureExecutor.java").read_text()
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
            self.assertIn("GraphCheckerHBaseSaslProtocol.connectionCreated(this,", client)
            self.assertIn("GraphCheckerHBaseSaslProtocol.bindHandler(saslHandler, this)", client)
            self.assertIn("GraphCheckerHBaseSaslProtocol.prepareResponse(this, response)",
                          sasl_client)
            self.assertIn("if (future.isSuccess()) frame.sent();", sasl_client)
            self.assertIn("GraphCheckerHBaseSaslProtocol.enterResponse(rpcServer, saslToken)",
                          sasl_server)
            self.assertIn("saslServer.evaluateResponse(graphScope.saslToken)", sasl_server)
            self.assertNotIn("GraphCheckerHBaseProtocol.responseSent", rpc_server)
            self.assertIn("putToMetaTable(connection, put);\n"
                          "    GraphCheckerHBaseMetaState.writeAck(put);", meta)
            self.assertIn("GraphCheckerHBaseMetaState.readCell(cell);\n"
                          "      return parsed;", meta)
            self.assertIn("GraphCheckerHBaseMetaState.readCell(cell);\n"
                          "      return Optional.of(parsed);", async_meta)
            self.assertIn("GraphCheckerHBaseProcedureScope.capture(proc);\n"
                          "    scheduler.addBack(proc);", procedure)
            self.assertIn("GraphCheckerHBaseProcedureScope.capture(subproc);\n"
                          "      scheduler.addFront(subproc);", procedure)
            self.assertIn("GraphCheckerHBaseProcedureScope.enter(proc);", procedure)
            self.assertIn("GraphCheckerHBaseProcedureScope.exit(graphScope);", procedure)
            self.assertIn("optional bytes mallory_graph_context = 4;",
                          (root / "hbase-protocol-shaded/src/main/protobuf/RPC.proto").read_text())


if __name__ == "__main__":
    unittest.main()
