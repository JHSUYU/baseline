#!/usr/bin/env python3
"""Apply the isolated GraphChecker protocol port to an HBase 2.6.6 checkout.

The script requires exact source anchors, refuses partial/already patched trees,
and writes no file until every edit has been checked. Use --check for a dry run.
"""

import argparse
from pathlib import Path


DEPENDENCY = """    <dependency>
      <groupId>edu.uva.liftlab.mallory</groupId>
      <artifactId>mallory-graphchecker-runtime</artifactId>
      <version>1.0-SNAPSHOT</version>
    </dependency>
"""


def edit(source: str, before: str, after: str, name: str) -> str:
    count = source.count(before)
    if count != 1:
        raise ValueError(f"{name}: expected one source anchor, found {count}")
    return source.replace(before, after, 1)


def patches() -> dict[str, list[tuple[str, str]]]:
    client = "hbase-client/src/main/java/org/apache/hadoop/hbase/ipc/"
    server = "hbase-server/src/main/java/org/apache/hadoop/hbase/ipc/"
    return {
        "hbase-protocol-shaded/src/main/protobuf/RPC.proto": [(
            "message ResponseHeader {\n  optional uint32 call_id = 1;\n",
            "message ResponseHeader {\n  optional uint32 call_id = 1;\n"
            "  optional bytes mallory_graph_context = 4;\n")],
        "hbase-protocol/src/main/protobuf/RPC.proto": [(
            "message ResponseHeader {\n  optional uint32 call_id = 1;\n",
            "message ResponseHeader {\n  optional uint32 call_id = 1;\n"
            "  optional bytes mallory_graph_context = 4;\n")],
        "hbase-client/pom.xml": [(
            "  <artifactId>hbase-client</artifactId>\n"
            "  <name>Apache HBase - Client</name>\n"
            "  <description>Client of HBase</description>\n\n"
            "  <dependencies>\n",
            "  <artifactId>hbase-client</artifactId>\n"
            "  <name>Apache HBase - Client</name>\n"
            "  <description>Client of HBase</description>\n\n"
            "  <dependencies>\n" + DEPENDENCY)],
        "hbase-server/pom.xml": [(
            "    <hbase.webapps.dir>hbase-webapps</hbase.webapps.dir>\n"
            "  </properties>\n  <dependencies>\n",
            "    <hbase.webapps.dir>hbase-webapps</hbase.webapps.dir>\n"
            "  </properties>\n  <dependencies>\n" + DEPENDENCY)],
        "hbase-procedure/pom.xml": [(
            "  <description>Procedure Framework</description>\n\n  <dependencies>\n",
            "  <description>Procedure Framework</description>\n\n"
            "  <dependencies>\n" + DEPENDENCY)],
        "hbase-procedure/src/main/java/org/apache/hadoop/hbase/procedure2/ProcedureExecutor.java": [(
            "    procedures.put(currentProcId, proc);\n"
            "    sendProcedureAddedNotification(currentProcId);\n"
            "    scheduler.addBack(proc);\n",
            "    procedures.put(currentProcId, proc);\n"
            "    sendProcedureAddedNotification(currentProcId);\n"
            "    GraphCheckerHBaseProcedureScope.capture(proc);\n"
            "    scheduler.addBack(proc);\n"), (
            "      procedures.put(subproc.getProcId(), subproc);\n"
            "      scheduler.addFront(subproc);\n",
            "      procedures.put(subproc.getProcId(), subproc);\n"
            "      GraphCheckerHBaseProcedureScope.capture(subproc);\n"
            "      scheduler.addFront(subproc);\n"), (
            "          this.activeProcedure = proc;\n"
            "          lastUpdate = TraceUtil.trace(this::runProcedure, new ProcedureSpanBuilder(proc));\n",
            "          this.activeProcedure = proc;\n"
            "          long graphScope = GraphCheckerHBaseProcedureScope.enter(proc);\n"
            "          try {\n"
            "            lastUpdate = TraceUtil.trace(this::runProcedure, new ProcedureSpanBuilder(proc));\n"
            "          } finally {\n"
            "            GraphCheckerHBaseProcedureScope.exit(graphScope);\n"
            "          }\n")],
        client + "Call.java": [(
            "    this.span = Span.current();\n  }\n",
            "    this.span = Span.current();\n"
            "    GraphCheckerHBaseProtocol.clientCallCreated(this);\n  }\n")],
        "hbase-client/src/main/java/org/apache/hadoop/hbase/client/ConnectionImplementation.java": [(
            "    ThreadPoolExecutor tpe =\n"
            "      new ThreadPoolExecutor(coreThreads, maxThreads, keepAliveTime, TimeUnit.SECONDS, workQueue,\n",
            "    ThreadPoolExecutor tpe = new GraphCheckerContextThreadPoolExecutor(\n"
            "      coreThreads, maxThreads, keepAliveTime, TimeUnit.SECONDS, workQueue,\n")],
        client + "BlockingRpcCallback.java": [(
            "import org.apache.yetus.audience.InterfaceAudience;\n",
            "import org.apache.yetus.audience.InterfaceAudience;\n"
            "import edu.uva.liftlab.mallory.graphchecker.runtime.MessageDoors;\n"), (
            "  private boolean resultSet = false;\n",
            "  private boolean resultSet = false;\n"
            "  private final String malloryGraphVersion = java.util.UUID.randomUUID().toString() + \":1\";\n"), (
            "      resultSet = true;\n      this.notifyAll();\n",
            "      resultSet = true;\n"
            "      MessageDoors.stored(\"hbase-blocking-rpc-callback\", malloryGraphVersion, null);\n"
            "      this.notifyAll();\n"), (
            "    return result;\n  }\n}\n",
            "    MessageDoors.fetched(\"hbase-blocking-rpc-callback\", malloryGraphVersion, null);\n"
            "    return result;\n  }\n}\n")],
        "hbase-client/src/main/java/org/apache/hadoop/hbase/MetaTableAccessor.java": [(
            "    try {\n      return TableState.parseFrom(TableName.valueOf(r.getRow()),\n"
            "        Arrays.copyOfRange(cell.getValueArray(), cell.getValueOffset(),\n"
            "          cell.getValueOffset() + cell.getValueLength()));\n",
            "    try {\n      TableState parsed = TableState.parseFrom(TableName.valueOf(r.getRow()),\n"
            "        Arrays.copyOfRange(cell.getValueArray(), cell.getValueOffset(),\n"
            "          cell.getValueOffset() + cell.getValueLength()));\n"
            "      GraphCheckerHBaseMetaState.readCell(cell);\n"
            "      return parsed;\n"), (
            "    putToMetaTable(connection, put);\n    LOG.info(\"Updated {} in hbase:meta\", state);\n",
            "    putToMetaTable(connection, put);\n"
            "    GraphCheckerHBaseMetaState.writeAck(put);\n"
            "    LOG.info(\"Updated {} in hbase:meta\", state);\n")],
        "hbase-client/src/main/java/org/apache/hadoop/hbase/AsyncMetaTableAccessor.java": [(
            "      return Optional.of(\n"
            "        TableState.parseFrom(TableName.valueOf(r.getRow()), Arrays.copyOfRange(cell.getValueArray(),\n"
            "          cell.getValueOffset(), cell.getValueOffset() + cell.getValueLength())));\n",
            "      TableState parsed = TableState.parseFrom(TableName.valueOf(r.getRow()),\n"
            "        Arrays.copyOfRange(cell.getValueArray(), cell.getValueOffset(),\n"
            "          cell.getValueOffset() + cell.getValueLength()));\n"
            "      GraphCheckerHBaseMetaState.readCell(cell);\n"
            "      return Optional.of(parsed);\n")],
        client + "IPCUtil.java": [(
            "    builder.setTimeout(call.timeout);\n\n    return builder.build();\n",
            "    builder.setTimeout(call.timeout);\n"
            "    byte[] graphContext = GraphCheckerHBaseProtocol.prepareRequest(call);\n"
            "    if (graphContext.length > 0) {\n"
            "      builder.addAttribute(HBaseProtos.NameBytesPair.newBuilder()\n"
            "        .setName(GraphCheckerHBaseProtocol.REQUEST_ATTRIBUTE)\n"
            "        .setValue(UnsafeByteOperations.unsafeWrap(graphContext)).build());\n"
            "    }\n\n    return builder.build();\n")],
        client + "NettyRpcConnection.java": [(
            "              if (!future.isSuccess()) {\n"
            "                call.setException(toIOE(future.cause()));\n"
            "              }\n",
            "              if (!future.isSuccess()) {\n"
            "                call.setException(toIOE(future.cause()));\n"
            "              } else {\n"
            "                GraphCheckerHBaseProtocol.requestSent(call);\n"
            "              }\n"), (
            "    header.writeTo(new ByteBufOutputStream(this.connectionHeaderWithLength));\n",
            "    header.writeTo(new ByteBufOutputStream(this.connectionHeaderWithLength));\n"
            "    GraphCheckerHBaseSaslProtocol.connectionCreated(this, remoteId.getServiceName());\n"), (
            "        rpcClient.fallbackAllowed, this.rpcClient.conf);\n"
            "    } catch (IOException e) {\n",
            "        rpcClient.fallbackAllowed, this.rpcClient.conf);\n"
            "      GraphCheckerHBaseSaslProtocol.bindHandler(saslHandler, this);\n"
            "    } catch (IOException e) {\n")],
        "hbase-client/src/main/java/org/apache/hadoop/hbase/security/NettyHBaseSaslRpcClientHandler.java": [(
            "import org.apache.hadoop.hbase.ipc.FallbackDisallowedException;\n",
            "import org.apache.hadoop.hbase.ipc.FallbackDisallowedException;\n"
            "import org.apache.hadoop.hbase.ipc.GraphCheckerHBaseSaslProtocol;\n"), (
            "import org.apache.hbase.thirdparty.io.netty.channel.ChannelHandlerContext;\n",
            "import org.apache.hbase.thirdparty.io.netty.channel.ChannelHandlerContext;\n"
            "import org.apache.hbase.thirdparty.io.netty.channel.ChannelFuture;\n"), (
            "    NettyFutureUtils.safeWriteAndFlush(ctx,\n"
            "      ctx.alloc().buffer(4 + response.length).writeInt(response.length).writeBytes(response));\n",
            "    GraphCheckerHBaseSaslProtocol.Frame frame =\n"
            "      GraphCheckerHBaseSaslProtocol.prepareResponse(this, response);\n"
            "    ChannelFuture write = ctx.writeAndFlush(ctx.alloc().buffer(4 + frame.payload.length)\n"
            "      .writeInt(frame.payload.length).writeBytes(frame.payload));\n"
            "    NettyFutureUtils.consume(write);\n"
            "    NettyFutureUtils.addListener(write, future -> {\n"
            "      if (future.isSuccess()) frame.sent();\n"
            "    });\n")],
        client + "BlockingRpcConnection.java": [(
            "        call.callStats.setRequestSizeBytes(write(this.out, requestHeader, call.param, cellBlock));\n",
            "        call.callStats.setRequestSizeBytes(write(this.out, requestHeader, call.param, cellBlock));\n"
            "        GraphCheckerHBaseProtocol.requestSent(call);\n")],
        client + "RpcConnection.java": [(
            "    call.callStats.setResponseSizeBytes(totalSize);\n"
            "    if (remoteExc != null) {\n"
            "      call.setException(remoteExc);\n"
            "      return;\n"
            "    }\n"
            "    try {\n"
            "      finishCall(responseHeader, in, call);\n"
            "    } catch (IOException e) {\n",
            "    try (GraphCheckerHBaseProtocol.ResponseScope graphScope =\n"
            "      GraphCheckerHBaseProtocol.enterResponse(\n"
            "        responseHeader.getMalloryGraphContext().toByteArray(), call)) {\n"
            "      call.callStats.setResponseSizeBytes(totalSize);\n"
            "      if (remoteExc != null) {\n"
            "        call.setException(remoteExc);\n"
            "        return;\n"
            "      }\n"
            "      try {\n"
            "        finishCall(responseHeader, in, call);\n"
            "      } catch (IOException e) {\n"), (
            "      throw e;\n    }\n  }\n}\n",
            "      throw e;\n      }\n    }\n  }\n}\n")],
        server + "CallRunner.java": [(
            "  public void run() {\n    try (Scope ignored = span.makeCurrent()) {\n",
            "  public void run() {\n"
            "    try (Scope ignored = span.makeCurrent();\n"
            "      GraphCheckerHBaseProtocol.RequestScope graphScope =\n"
            "        GraphCheckerHBaseProtocol.enterRequest(rpcServer, call)) {\n"), (
            "  public void drop() {\n    try (Scope ignored = span.makeCurrent()) {\n",
            "  public void drop() {\n"
            "    try (Scope ignored = span.makeCurrent();\n"
            "      GraphCheckerHBaseProtocol.RequestScope graphScope =\n"
            "        GraphCheckerHBaseProtocol.enterRequest(rpcServer, call)) {\n")],
        server + "NettyHBaseSaslRpcServerHandler.java": [(
            "import org.apache.hadoop.hbase.security.HBaseSaslRpcServer;\n",
            "import org.apache.hadoop.hbase.security.HBaseSaslRpcServer;\n"
            "import org.apache.hadoop.hbase.ipc.GraphCheckerHBaseSaslProtocol.Scope;\n"), (
            "    byte[] replyToken = saslServer.evaluateResponse(saslToken);\n"
            "    if (replyToken != null) {\n",
            "    try (Scope graphScope = GraphCheckerHBaseSaslProtocol.enterResponse(rpcServer, saslToken)) {\n"
            "    byte[] replyToken = saslServer.evaluateResponse(graphScope.saslToken);\n"
            "    if (replyToken != null) {\n"), (
            "      p.remove(DECODER_NAME);\n"
            "    }\n"
            "  }\n\n"
            "  @Override\n"
            "  public void exceptionCaught",
            "      p.remove(DECODER_NAME);\n"
            "    }\n"
            "    }\n"
            "  }\n\n"
            "  @Override\n"
            "  public void exceptionCaught")],
        server + "ServerCall.java": [(
            "import org.apache.hbase.thirdparty.com.google.protobuf.BlockingService;\n",
            "import org.apache.hbase.thirdparty.com.google.protobuf.BlockingService;\n"
            "import org.apache.hbase.thirdparty.com.google.protobuf.ByteString;\n"), (
            "      Message header = headerBuilder.build();\n"
            "      ByteBuffer headerBuf = createHeaderAndMessageBytes(m, header, cellBlockSize, cellBlock);\n",
            "      byte[] graphContext = GraphCheckerHBaseProtocol.prepareResponse(this);\n"
            "      if (graphContext.length > 0) {\n"
            "        headerBuilder.setMalloryGraphContext(ByteString.copyFrom(graphContext));\n"
            "      }\n"
            "      Message header = headerBuilder.build();\n"
            "      ByteBuffer headerBuf = createHeaderAndMessageBytes(m, header, cellBlockSize, cellBlock);\n"), (
            "      setExceptionResponse(originalException, responseErrorMsg, headerBuilder);\n"
            "      Message header = headerBuilder.build();\n",
            "      setExceptionResponse(originalException, responseErrorMsg, headerBuilder);\n"
            "      byte[] graphContext = GraphCheckerHBaseProtocol.prepareResponse(this);\n"
            "      if (graphContext.length > 0) {\n"
            "        headerBuilder.setMalloryGraphContext(ByteString.copyFrom(graphContext));\n"
            "      }\n"
            "      Message header = headerBuilder.build();\n")],
        server + "NettyServerRpcConnection.java": [(
            "    NettyFutureUtils.safeWriteAndFlush(channel, resp);\n",
            "    NettyFutureUtils.addListener(channel.writeAndFlush(resp), future -> {\n"
            "      if (future.isSuccess()) {\n"
            "        GraphCheckerHBaseProtocol.responseSent(resp);\n"
            "      } else {\n"
            "        GraphCheckerHBaseProtocol.responseWriteFailed(resp);\n"
            "        NettyRpcServer.LOG.warn(\"RPC response write failed\", future.cause());\n"
            "      }\n"
            "    });\n")],
        server + "SimpleRpcServerResponder.java": [(
            "    if (!buf.hasRemaining()) {\n      resp.done();\n      return true;\n",
            "    if (!buf.hasRemaining()) {\n"
            "      GraphCheckerHBaseProtocol.responseSent(resp);\n"
            "      resp.done();\n      return true;\n")],
        "hbase-server/src/main/java/org/apache/hadoop/hbase/util/JVMClusterUtil.java": [(
            "import org.apache.hadoop.hbase.HConstants;\n",
            "import org.apache.hadoop.hbase.HConstants;\n"
            "import org.apache.hadoop.hbase.ipc.GraphCheckerHBaseProtocol;\n"), (
            "      this.regionServer = r;\n    }\n",
            "      this.regionServer = r;\n"
            "      GraphCheckerHBaseProtocol.registerMiniClusterNode(r, \"REGION_SERVER\", index);\n"
            "    }\n\n"
            "    @Override\n"
            "    public void run() {\n"
            "      long actor = GraphCheckerHBaseProtocol.enterMiniClusterActor(regionServer, \"REGION_SERVER\");\n"
            "      try {\n"
            "        super.run();\n"
            "      } finally {\n"
            "        GraphCheckerHBaseProtocol.exitMiniClusterActor(actor);\n"
            "      }\n"
            "    }\n"), (
            "      this.master = m;\n    }\n",
            "      this.master = m;\n"
            "      GraphCheckerHBaseProtocol.registerMiniClusterNode(m, \"MASTER\", index);\n"
            "    }\n\n"
            "    @Override\n"
            "    public void run() {\n"
            "      long actor = GraphCheckerHBaseProtocol.enterMiniClusterActor(master, \"MASTER\");\n"
            "      try {\n"
            "        super.run();\n"
            "      } finally {\n"
            "        GraphCheckerHBaseProtocol.exitMiniClusterActor(actor);\n"
            "      }\n"
            "    }\n")],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("hbase_root", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.hbase_root.resolve()
    changed: dict[Path, str] = {}
    for relative, replacements in patches().items():
        path = root / relative
        content = path.read_text(encoding="utf-8")
        for before, after in replacements:
            content = edit(content, before, after, relative)
        changed[path] = content
    bridge = root / "hbase-client/src/main/java/org/apache/hadoop/hbase/ipc/GraphCheckerHBaseProtocol.java"
    if bridge.exists():
        raise ValueError(f"already patched: {bridge}")
    changed[bridge] = (Path(__file__).parent / "src/GraphCheckerHBaseProtocol.java").read_text(
        encoding="utf-8")
    pool = root / "hbase-client/src/main/java/org/apache/hadoop/hbase/client/GraphCheckerContextThreadPoolExecutor.java"
    if pool.exists():
        raise ValueError(f"already patched: {pool}")
    changed[pool] = (Path(__file__).parent / "src/GraphCheckerContextThreadPoolExecutor.java").read_text(
        encoding="utf-8")
    sasl = root / "hbase-client/src/main/java/org/apache/hadoop/hbase/ipc/GraphCheckerHBaseSaslProtocol.java"
    if sasl.exists():
        raise ValueError(f"already patched: {sasl}")
    changed[sasl] = (Path(__file__).parent / "src/GraphCheckerHBaseSaslProtocol.java").read_text(
        encoding="utf-8")
    meta_state = root / "hbase-client/src/main/java/org/apache/hadoop/hbase/GraphCheckerHBaseMetaState.java"
    if meta_state.exists():
        raise ValueError(f"already patched: {meta_state}")
    changed[meta_state] = (Path(__file__).parent / "src/GraphCheckerHBaseMetaState.java").read_text(
        encoding="utf-8")
    procedure_scope = root / "hbase-procedure/src/main/java/org/apache/hadoop/hbase/procedure2/GraphCheckerHBaseProcedureScope.java"
    if procedure_scope.exists():
        raise ValueError(f"already patched: {procedure_scope}")
    changed[procedure_scope] = (Path(__file__).parent / "src/GraphCheckerHBaseProcedureScope.java").read_text(
        encoding="utf-8")
    if not args.check:
        for path, content in changed.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    print(f"{'checked' if args.check else 'patched'} {len(changed)} HBase 2.6.6 files")


if __name__ == "__main__":
    main()
