package edu.uva.liftlab.mallory.adapters.hdfs.graphchecker;

import javassist.CannotCompileException;
import javassist.ClassPool;
import javassist.CtClass;
import javassist.CtMethod;
import javassist.expr.ExprEditor;
import javassist.expr.MethodCall;
import javassist.expr.NewExpr;

/**
 * Patches copies of Hadoop 3.4.3 classes in an isolated classpath overlay.
 * The original JUnit and Hadoop source tree are untouched. Every expected
 * bytecode boundary is checked, so a changed Hadoop build fails closed.
 */
public final class PatchEmbeddedIpc {
  private static final String BRIDGE =
      "org.apache.hadoop.ipc.MalloryEmbeddedIpcBridge";

  private PatchEmbeddedIpc() { }

  public static void main(String[] args) throws Exception {
    if (args.length != 4) {
      throw new IllegalArgumentException(
          "usage: PatchEmbeddedIpc <overlay> <hadoop-common.jar> <hadoop-hdfs.jar> <hadoop-hdfs-tests.jar>");
    }
    ClassPool pool = ClassPool.getDefault();
    pool.insertClassPath(args[0]);
    pool.appendClassPath(args[1]);
    pool.appendClassPath(args[2]);
    pool.appendClassPath(args[3]);

    CtClass cluster = pool.get("org.apache.hadoop.hdfs.MiniDFSCluster");
    CtMethod wait = cluster.getDeclaredMethod("waitActive", new CtClass[0]);
    wait.insertAfter(BRIDGE + ".registerCluster(this);");
    final int[] earlyNameNode = {0};
    cluster.getDeclaredMethod("createNameNode").instrument(new ExprEditor() {
      @Override public void edit(MethodCall call) throws CannotCompileException {
        if (call.getClassName().equals(
                "org.apache.hadoop.hdfs.server.namenode.NameNode")
            && call.getMethodName().equals("createNameNode")) {
          call.replace("{ $_ = $proceed($$); if ($_ != null) " + BRIDGE
              + ".registerEarlyNameNode(this, $_); }");
          earlyNameNode[0]++;
        }
      }
    });
    requireOne("MiniDFSCluster.createNameNode early source", earlyNameNode[0]);
    final int[] earlyDataNode = {0};
    final int[] initialConstruction = {0};
    for (CtMethod startDataNodes : cluster.getDeclaredMethods("startDataNodes")) {
      startDataNodes.instrument(new ExprEditor() {
        @Override public void edit(MethodCall call) throws CannotCompileException {
          if (call.getClassName().equals(
                  "org.apache.hadoop.hdfs.server.datanode.DataNode")
              && call.getMethodName().equals("instantiateDataNode")) {
            call.replace("{ " + BRIDGE
                + ".beginConstructInitialDataNode(this);"
                + " try { $_ = $proceed($$); } finally { " + BRIDGE
                + ".endConstructDataNode(); } }");
            initialConstruction[0]++;
          } else if (call.getClassName().equals(
                  "org.apache.hadoop.hdfs.server.datanode.DataNode")
              && call.getMethodName().equals("runDatanodeDaemon")) {
            call.replace("{ " + BRIDGE
                + ".registerEarlyDataNode(this, $0); $proceed($$); }");
            earlyDataNode[0]++;
          }
        }
      });
    }
    requireOne("MiniDFSCluster initial DataNode construction",
        initialConstruction[0]);
    requireOne("MiniDFSCluster DataNode daemon early source", earlyDataNode[0]);
    // Here $1 must be the enclosing method's DataNodeProperties parameter,
    // not the first argument of the nested DataNode.createDataNode call.
    CtMethod restartDataNode = cluster.getDeclaredMethod("restartDataNode",
        new CtClass[] {
            pool.get("org.apache.hadoop.hdfs.MiniDFSCluster$DataNodeProperties"),
            CtClass.booleanType});
    restartDataNode.insertBefore(BRIDGE
        + ".beginConstructRestartDataNode($1);");
    restartDataNode.insertAfter(BRIDGE + ".endConstructDataNode();", true);
    cluster.writeFile(args[0]);
    cluster.detach();

    CtClass journalBuilder = pool.get(
        "org.apache.hadoop.hdfs.qjournal.MiniJournalCluster$Builder");
    journalBuilder.getDeclaredMethod("build", new CtClass[0])
        .insertAfter("if ($_ != null) " + BRIDGE
            + ".registerJournalCluster($_);");
    journalBuilder.writeFile(args[0]);
    journalBuilder.detach();

    CtClass journalCluster = pool.get(
        "org.apache.hadoop.hdfs.qjournal.MiniJournalCluster");
    journalCluster.getDeclaredMethod("start", new CtClass[0])
        .insertAfter(BRIDGE + ".registerJournalCluster(this);");
    journalCluster.getDeclaredMethod("restartJournalNode",
        new CtClass[] {CtClass.intType})
        .insertAfter(BRIDGE + ".registerJournalRestart(this, $1);");
    journalCluster.writeFile(args[0]);
    journalCluster.detach();

    CtClass loggerChannel = pool.get(
        "org.apache.hadoop.hdfs.qjournal.client.IPCLoggerChannel");
    final int[] submittedCallables = {0};
    final int[] submittedRunnables = {0};
    for (CtMethod method : loggerChannel.getDeclaredMethods()) {
      method.instrument(new ExprEditor() {
        @Override public void edit(MethodCall call) throws CannotCompileException {
          if (!call.getClassName().equals(
                  "org.apache.hadoop.thirdparty.com.google.common.util.concurrent.ListeningExecutorService")
              || !call.getMethodName().equals("submit")) return;
          String signature = call.getSignature();
          if (signature.startsWith("(Ljava/util/concurrent/Callable;)")) {
            call.replace("{ $_ = $proceed(" + BRIDGE
                + ".wrapJournalCallable($1)); }");
            submittedCallables[0]++;
          } else if (signature.startsWith("(Ljava/lang/Runnable;)")) {
            call.replace("{ $_ = $proceed(" + BRIDGE
                + ".wrapJournalRunnable($1)); }");
            submittedRunnables[0]++;
          } else {
            throw new CannotCompileException(
                "unsupported IPCLoggerChannel executor submit " + signature);
          }
        }
      });
    }
    if (submittedCallables[0] == 0 || submittedRunnables[0] == 0) {
      throw new IllegalStateException("QJM executor handoff changed: callable="
          + submittedCallables[0] + ", runnable=" + submittedRunnables[0]);
    }
    loggerChannel.writeFile(args[0]);
    loggerChannel.detach();

    CtClass recoveryWorker = pool.get(
        "org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker");
    final int[] recoveryDaemons = {0};
    recoveryWorker.getDeclaredMethod("recoverBlocks").instrument(
        new ExprEditor() {
          @Override public void edit(NewExpr created)
              throws CannotCompileException {
            if (created.getClassName().equals("org.apache.hadoop.util.Daemon")) {
              created.replace("{ $_ = $proceed($1, " + BRIDGE
                  + ".wrapBlockRecoveryRunnable($2, this.datanode)); }");
              recoveryDaemons[0]++;
            }
          }
        });
    requireOne("BlockRecoveryWorker Daemon handoff", recoveryDaemons[0]);
    recoveryWorker.writeFile(args[0]);
    recoveryWorker.detach();

    CtClass dataNode = pool.get(
        "org.apache.hadoop.hdfs.server.datanode.DataNode");
    CtMethod startDataNode = dataNode.getDeclaredMethod("startDataNode");
    final int[] bpRefresh = {0};
    startDataNode.instrument(new ExprEditor() {
      @Override public void edit(MethodCall call) throws CannotCompileException {
        if (call.getClassName().equals(
                "org.apache.hadoop.hdfs.server.datanode.BlockPoolManager")
            && call.getMethodName().equals("refreshNamenodes")) {
          call.replace("{ long malloryTick = " + BRIDGE
              + ".beforeInitialBpRefresh(this);"
              + " try { $proceed($$); } finally { " + BRIDGE
              + ".afterInitialBpRefresh(malloryTick); } }");
          bpRefresh[0]++;
        }
      }
    });
    requireOne("DataNode initial block-pool refresh", bpRefresh[0]);
    dataNode.writeFile(args[0]);
    dataNode.detach();

    CtClass bpActor = pool.get(
        "org.apache.hadoop.hdfs.server.datanode.BPServiceActor");
    CtMethod actorStart = bpActor.getDeclaredMethod("start", new CtClass[0]);
    final int[] actorThreadStart = {0};
    actorStart.instrument(new ExprEditor() {
      @Override public void edit(MethodCall call) throws CannotCompileException {
        if (call.getClassName().equals("java.lang.Thread")
            && call.getMethodName().equals("start")) {
          call.replace("{ " + BRIDGE
              + ".bpActorStarting(this, this.dn);"
              + " try { $proceed($$); }"
              + " catch (java.lang.RuntimeException e) { " + BRIDGE
              + ".bpActorStartFailed(this); throw e; }"
              + " catch (java.lang.Error e) { " + BRIDGE
              + ".bpActorStartFailed(this); throw e; } }");
          actorThreadStart[0]++;
        }
      }
    });
    requireOne("BPServiceActor thread start", actorThreadStart[0]);
    CtMethod actorRun = bpActor.getDeclaredMethod("run", new CtClass[0]);
    actorRun.insertBefore(BRIDGE + ".bpActorRun(this);");
    actorRun.insertAfter(BRIDGE + ".bpActorExit();", true);
    bpActor.writeFile(args[0]);
    bpActor.detach();

    CtClass admin = pool.get("org.apache.hadoop.hdfs.tools.DFSAdmin");
    CtMethod delete = admin.getDeclaredMethod("deleteBlockPool");
    delete.insertBefore(BRIDGE + ".beginAdmin(this, $1, $2);");
    delete.insertAfter(BRIDGE + ".endAdmin();", true);
    admin.writeFile(args[0]);
    admin.detach();

    CtClass connection = pool.get("org.apache.hadoop.ipc.Client$Connection");
    CtMethod send = connection.getDeclaredMethod("sendRpcRequest");
    send.insertBefore(BRIDGE + ".clientPrepare($1, this);");
    final int[] offered = {0};
    send.instrument(new ExprEditor() {
      @Override public void edit(MethodCall call) throws CannotCompileException {
        if (call.getClassName().equals("java.util.concurrent.SynchronousQueue")
            && call.getMethodName().equals("offer")) {
          call.replace("{ $_ = $proceed($$); if ($_) " + BRIDGE
              + ".clientQueueAccepted($1); }");
          offered[0]++;
        }
      }
    });
    requireOne("SynchronousQueue.offer", offered[0]);
    send.insertAfter(BRIDGE + ".clientQueueAttemptDone($1);", true);
    connection.writeFile(args[0]);
    connection.detach();

    CtClass sender = pool.get(
        "org.apache.hadoop.ipc.Client$Connection$RpcRequestSender");
    CtMethod senderRun = sender.getDeclaredMethod("run", new CtClass[0]);
    final int[] polled = {0};
    final int[] written = {0};
    senderRun.instrument(new ExprEditor() {
      @Override public void edit(MethodCall call) throws CannotCompileException {
        if (call.getClassName().equals("java.util.concurrent.SynchronousQueue")
            && call.getMethodName().equals("poll")) {
          call.replace("{ $_ = $proceed($$); if ($_ != null) " + BRIDGE
              + ".clientDequeued($_); }");
          polled[0]++;
        } else if (call.getMethodName().equals("sendRequest")) {
          call.replace("{ try { $proceed($$); " + BRIDGE
              + ".clientSent(); } catch (java.io.IOException e) { "
              + BRIDGE + ".clientSendFailed(e); throw e; } }");
          written[0]++;
        }
      }
    });
    requireOne("RpcRequestSender.poll", polled[0]);
    requireOne("IpcStreams.sendRequest", written[0]);
    sender.writeFile(args[0]);
    sender.detach();

    CtClass serverCall = pool.get("org.apache.hadoop.ipc.Server$RpcCall");
    CtMethod run = serverCall.getDeclaredMethod("run", new CtClass[0]);
    final int[] dispatched = {0};
    run.instrument(new ExprEditor() {
      @Override public void edit(MethodCall call) throws CannotCompileException {
        if (call.getMethodName().equals("call")
            && call.getSignature().endsWith(")Lorg/apache/hadoop/io/Writable;")) {
          call.replace("{ " + BRIDGE
              + ".serverEnter(this, this.connection.getServer());"
              + " try { $_ = $proceed($$); } finally { " + BRIDGE
              + ".serverExit(); } }");
          dispatched[0]++;
        }
      }
    });
    requireOne("RpcCall.call dispatch", dispatched[0]);
    serverCall.writeFile(args[0]);
    serverCall.detach();

    CtClass serverConnection = pool.get("org.apache.hadoop.ipc.Server$Connection");
    CtMethod response = serverConnection.getDeclaredMethod("sendResponse");
    response.insertBefore(BRIDGE + ".serverResponsePrepare($1);");
    response.insertAfter(BRIDGE + ".serverResponseSent($1);");
    response.addCatch("{ " + BRIDGE
        + ".serverResponseFailed($1, $e); throw $e; }",
        pool.get("java.io.IOException"));
    serverConnection.writeFile(args[0]);
    serverConnection.detach();

    CtClass client = pool.get("org.apache.hadoop.ipc.Client");
    CtMethod receive = client.getDeclaredMethod("getRpcResponse");
    receive.insertAfter(BRIDGE
        + ".clientResponseConsumed($1, $2, $_);");
    receive.addCatch("{ " + BRIDGE
        + ".clientErrorConsumed($1, $2, $e); throw $e; }",
        pool.get("java.io.IOException"));
    client.writeFile(args[0]);
    client.detach();
  }

  private static void requireOne(String boundary, int count) {
    if (count != 1) {
      throw new IllegalStateException("expected one " + boundary + ", saw " + count);
    }
  }
}
