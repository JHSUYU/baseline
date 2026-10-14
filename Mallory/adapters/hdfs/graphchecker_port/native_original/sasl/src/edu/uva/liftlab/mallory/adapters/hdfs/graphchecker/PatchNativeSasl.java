package edu.uva.liftlab.mallory.adapters.hdfs.graphchecker;

import javassist.CannotCompileException;
import javassist.ClassPool;
import javassist.CtClass;
import javassist.CtMethod;
import javassist.LoaderClassPath;
import javassist.expr.ExprEditor;
import javassist.expr.MethodCall;

/** Patches the common SASL envelope operations, independent of a target. */
public final class PatchNativeSasl {
  private static final String DOORS =
      "org.apache.hadoop.hdfs.protocol.datatransfer.sasl.NativeHdfsSaslDoors";
  private static final String PROTO =
      "org.apache.hadoop.hdfs.protocol.proto.DataTransferProtos$DataTransferEncryptorMessageProto";

  private PatchNativeSasl() { }

  public static void main(String[] args) throws Exception {
    if (args.length != 3) {
      throw new IllegalArgumentException(
          "usage: PatchNativeSasl <original-classes> <dependency-cp> <output>");
    }
    ClassPool pool = new ClassPool(false);
    pool.appendClassPath(args[0]);
    for (String entry : args[1].split(":")) {
      if (!entry.isEmpty()) pool.appendClassPath(entry);
    }
    pool.appendClassPath(new LoaderClassPath(PatchNativeSasl.class.getClassLoader()));

    CtClass util = pool.get(
        "org.apache.hadoop.hdfs.protocol.datatransfer.sasl.DataTransferSaslUtil");
    final int[] reads = {0};
    final int[] writes = {0};
    for (CtMethod method : util.getDeclaredMethods()) {
      if (method.isEmpty()) continue;
      method.instrument(new ExprEditor() {
        @Override public void edit(MethodCall call) throws CannotCompileException {
          if (PROTO.equals(call.getClassName())
              && "parseFrom".equals(call.getMethodName())) {
            call.replace("{ $_ = " + DOORS + ".parse($1); }");
            reads[0]++;
          } else if (PROTO.equals(call.getClassName())
              && "writeDelimitedTo".equals(call.getMethodName())) {
            call.replace("{ " + DOORS + ".writeAndFlush($0, $1); }");
            writes[0]++;
          }
        }
      });
    }
    require("common SASL protobuf parse", reads[0], 1);
    require("SASL protobuf writes", writes[0], 3);
    util.writeFile(args[2]);
    util.detach();

    CtClass client = pool.get(
        "org.apache.hadoop.hdfs.protocol.datatransfer.sasl.SaslDataTransferClient");
    int handshakes = 0;
    for (CtMethod method : client.getDeclaredMethods("doSaslHandshake")) {
      method.insertBefore(DOORS + ".beginClient(this);");
      method.insertAfter(DOORS + ".endClient();", true);
      handshakes++;
    }
    require("SASL client handshake", handshakes, 1);
    client.writeFile(args[2]);
    client.detach();

    CtClass server = pool.get(
        "org.apache.hadoop.hdfs.protocol.datatransfer.sasl.SaslDataTransferServer");
    int serverHandshakes = 0;
    for (CtMethod method : server.getDeclaredMethods("doSaslHandshake")) {
      method.insertBefore(DOORS + ".beginServer(this);");
      method.insertAfter(DOORS + ".endServer();", true);
      serverHandshakes++;
    }
    require("SASL server handshake", serverHandshakes, 1);
    server.writeFile(args[2]);
    server.detach();

    CtClass streamer = pool.get("org.apache.hadoop.hdfs.DataStreamer");
    CtMethod streamerRun = streamer.getDeclaredMethod("run");
    streamerRun.insertBefore(DOORS + ".beginStreamer(this, this.src);");
    streamerRun.insertAfter(DOORS + ".endStreamer();", true);
    streamer.writeFile(args[2]);
    streamer.detach();

    CtClass dispatcher = pool.get(
        "org.apache.hadoop.hdfs.server.balancer.Dispatcher");
    final int[] moveSubmissions = {0};
    dispatcher.getDeclaredMethod("executePendingMove").instrument(
        new ExprEditor() {
          @Override public void edit(MethodCall call)
              throws CannotCompileException {
            if ("execute".equals(call.getMethodName())
                && call.getClassName().startsWith("java.util.concurrent.")) {
              call.replace("{ $proceed(" + DOORS
                  + ".carry($1, \"Dispatcher.executePendingMove\")); }");
              moveSubmissions[0]++;
            }
          }
        });
    require("Balancer move executor handoff", moveSubmissions[0], 1);
    final int[] dispatchSubmissions = {0};
    dispatcher.getDeclaredMethod("dispatchBlockMoves").instrument(
        new ExprEditor() {
          @Override public void edit(MethodCall call)
              throws CannotCompileException {
            if ("submit".equals(call.getMethodName())
                && call.getClassName().startsWith("java.util.concurrent.")) {
              call.replace("{ $_ = $proceed(" + DOORS
                  + ".carry($1, \"Dispatcher.dispatchBlockMoves\")); }");
              dispatchSubmissions[0]++;
            }
          }
        });
    require("Balancer dispatcher executor handoff", dispatchSubmissions[0], 1);
    dispatcher.writeFile(args[2]);
    dispatcher.detach();
  }

  private static void require(String label, int actual, int expected) {
    if (actual != expected) {
      throw new IllegalStateException(label + ": expected " + expected
          + ", found " + actual);
    }
  }
}
