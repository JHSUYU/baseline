import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.InsnList;
import org.objectweb.asm.tree.InsnNode;
import org.objectweb.asm.tree.LabelNode;
import org.objectweb.asm.tree.LdcInsnNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.TryCatchBlockNode;
import org.objectweb.asm.tree.VarInsnNode;

/**
 * Post-weave adapter for the released Hadoop 3.4.3 binary.  Only the
 * SASL client/server methods open one DataNode request identity and record
 * the embedded-cluster TCP exchange without changing Hadoop wire bytes.
 */
public final class PatchSaslReceive implements Opcodes {
    private static final String SASL_METHOD_DESC = "(Lorg/apache/hadoop/hdfs/net/Peer;"
            + "Ljava/io/OutputStream;Ljava/io/InputStream;I"
            + "Lorg/apache/hadoop/hdfs/protocol/DatanodeID;)"
            + "Lorg/apache/hadoop/hdfs/protocol/datatransfer/IOStreamPair;";
    private static final String REGISTRATION_METHOD_DESC = "(Lorg/apache/hadoop/hdfs/server/datanode/BPServiceActor;"
            + "Lorg/apache/hadoop/hdfs/server/protocol/DatanodeRegistration;)V";
    private static final String PEER_SEND_DESC = "(Lorg/apache/hadoop/hdfs/net/Peer;"
            + "Lorg/apache/hadoop/hdfs/protocol/datatransfer/sasl/DataEncryptionKeyFactory;"
            + "Lorg/apache/hadoop/security/token/Token;"
            + "Lorg/apache/hadoop/hdfs/protocol/DatanodeID;)"
            + "Lorg/apache/hadoop/hdfs/net/Peer;";
    private static final String NEW_SOCKET_SEND_DESC = "(Ljava/net/Socket;"
            + "Ljava/io/OutputStream;Ljava/io/InputStream;"
            + "Lorg/apache/hadoop/hdfs/protocol/datatransfer/sasl/DataEncryptionKeyFactory;"
            + "Lorg/apache/hadoop/security/token/Token;"
            + "Lorg/apache/hadoop/hdfs/protocol/DatanodeID;)"
            + "Lorg/apache/hadoop/hdfs/protocol/datatransfer/IOStreamPair;";
    private static final String HANDSHAKE_DESC = "(Ljava/net/InetAddress;"
            + "Ljava/io/OutputStream;Ljava/io/InputStream;Ljava/lang/String;"
            + "Ljava/util/Map;Ljavax/security/auth/callback/CallbackHandler;"
            + "Lorg/apache/hadoop/security/token/Token;)"
            + "Lorg/apache/hadoop/hdfs/protocol/datatransfer/IOStreamPair;";
    private static final String HELPER =
            "edu/uva/liftlab/graphchecker/runtime/HdfsSaslRequestIdentity";
    private static final String SCOPE = "L" + HELPER + "$Scope;";

    public static void main(String[] args) throws Exception {
        if (args.length != 3) {
            throw new IllegalArgumentException(
                    "sasl|registration|client input-class output-class");
        }
        boolean sasl = args[0].equals("sasl");
        boolean registration = args[0].equals("registration");
        boolean client = args[0].equals("client");
        if (!sasl && !registration && !client) {
            throw new IllegalArgumentException("unknown mode " + args[0]);
        }
        Path input = Paths.get(args[1]);
        Path output = Paths.get(args[2]);
        ClassNode node = new ClassNode();
        new ClassReader(Files.readAllBytes(input)).accept(node, 0);
        int patched = 0;
        for (MethodNode method : node.methods) {
            if (sasl && method.name.equals("receive")
                    && method.desc.equals(SASL_METHOD_DESC)) {
                patchIdentity(method, true);
                patched++;
            } else if (sasl && method.name.equals("getEncryptionKeyFromUserName")
                    && method.desc.equals("(Ljava/lang/String;)[B")) {
                patchServerReceive(method);
                patched++;
            } else if (registration && method.name.equals("registrationSucceeded")
                    && method.desc.equals(REGISTRATION_METHOD_DESC)) {
                patchIdentity(method, false);
                patched++;
            } else if (client && method.name.equals("peerSend")
                    && method.desc.equals(PEER_SEND_DESC)) {
                patchClientEndpoint(method, true);
                patched++;
            } else if (client && method.name.equals("newSocketSend")
                    && method.desc.equals(NEW_SOCKET_SEND_DESC)) {
                patchClientEndpoint(method, false);
                patched++;
            } else if (client && method.name.equals("doSaslHandshake")
                    && method.desc.equals(HANDSHAKE_DESC)) {
                patchClientSend(method);
                patched++;
            }
        }
        int expected = client ? 3 : sasl ? 2 : 1;
        if (patched != expected) {
            throw new IllegalStateException("expected " + expected + " methods, found "
                    + patched);
        }
        ClassWriter writer = new ClassWriter(
                ClassWriter.COMPUTE_MAXS | ClassWriter.COMPUTE_FRAMES);
        node.accept(writer);
        Files.createDirectories(output.getParent());
        Files.write(output, writer.toByteArray());
    }

    private static void patchIdentity(MethodNode method, boolean sasl) {
        int scope = method.maxLocals++;
        int thrown = method.maxLocals++;
        LabelNode start = new LabelNode();
        LabelNode end = new LabelNode();
        LabelNode handler = new LabelNode();
        InsnList entry = new InsnList();
        entry.add(new VarInsnNode(ALOAD, 0));
        entry.add(new VarInsnNode(ALOAD, sasl ? 5 : 2));
        entry.add(new MethodInsnNode(INVOKEVIRTUAL,
                sasl ? "org/apache/hadoop/hdfs/protocol/DatanodeID"
                     : "org/apache/hadoop/hdfs/server/protocol/DatanodeRegistration",
                "getDatanodeUuid", "()Ljava/lang/String;", false));
        if (sasl) {
            entry.add(new LdcInsnNode("SASL_DATA_TRANSFER"));
            entry.add(new VarInsnNode(ALOAD, 1));
            entry.add(new MethodInsnNode(INVOKEINTERFACE,
                    "org/apache/hadoop/hdfs/net/Peer",
                    "getRemoteAddressString", "()Ljava/lang/String;", true));
        } else {
            entry.add(new org.objectweb.asm.tree.LdcInsnNode("BLOCKPOOL_REGISTER"));
        }
        entry.add(new MethodInsnNode(INVOKESTATIC, HELPER, "enter",
                sasl ? "(Ljava/lang/Object;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)" + SCOPE
                     : "(Ljava/lang/Object;Ljava/lang/String;Ljava/lang/String;)" + SCOPE,
                false));
        entry.add(new VarInsnNode(ASTORE, scope));
        entry.add(start);
        method.instructions.insertBefore(method.instructions.getFirst(), entry);

        for (AbstractInsnNode current = method.instructions.getFirst();
             current != null; ) {
            AbstractInsnNode next = current.getNext();
            int opcode = current.getOpcode();
            if (opcode == ARETURN || opcode == IRETURN || opcode == LRETURN
                    || opcode == FRETURN || opcode == DRETURN
                    || opcode == RETURN) {
                InsnList leave = new InsnList();
                leave.add(new VarInsnNode(ALOAD, scope));
                leave.add(new MethodInsnNode(INVOKESTATIC, HELPER, "exit",
                        "(" + SCOPE + ")V", false));
                method.instructions.insertBefore(current, leave);
            }
            current = next;
        }
        method.instructions.add(end);
        method.instructions.add(handler);
        method.instructions.add(new VarInsnNode(ASTORE, thrown));
        method.instructions.add(new VarInsnNode(ALOAD, scope));
        method.instructions.add(new MethodInsnNode(INVOKESTATIC, HELPER,
                "exit", "(" + SCOPE + ")V", false));
        method.instructions.add(new VarInsnNode(ALOAD, thrown));
        method.instructions.add(new InsnNode(ATHROW));
        method.tryCatchBlocks.add(new TryCatchBlockNode(start, end, handler,
                "java/lang/Throwable"));
    }

    private static void patchClientEndpoint(MethodNode method, boolean peer) {
        InsnList entry = new InsnList();
        entry.add(new VarInsnNode(ALOAD, 1));
        if (peer) {
            entry.add(new MethodInsnNode(INVOKEINTERFACE,
                    "org/apache/hadoop/hdfs/net/Peer", "getLocalAddressString",
                    "()Ljava/lang/String;", true));
        } else {
            entry.add(new MethodInsnNode(INVOKEVIRTUAL, "java/net/Socket",
                    "getLocalSocketAddress", "()Ljava/net/SocketAddress;", false));
            entry.add(new MethodInsnNode(INVOKEVIRTUAL, "java/net/SocketAddress",
                    "toString", "()Ljava/lang/String;", false));
        }
        entry.add(new MethodInsnNode(INVOKESTATIC, HELPER, "clientEndpoint",
                "(Ljava/lang/String;)V", false));
        method.instructions.insertBefore(method.instructions.getFirst(), entry);
        addFinally(method, "clearClientEndpoint");
    }

    private static void patchClientSend(MethodNode method) {
        int userName = method.maxLocals++;
        InsnList capture = new InsnList();
        capture.add(new VarInsnNode(ALOAD, 4));
        capture.add(new VarInsnNode(ASTORE, userName));
        method.instructions.insertBefore(method.instructions.getFirst(), capture);
        int count = 0;
        for (AbstractInsnNode current = method.instructions.getFirst();
             current != null; current = current.getNext()) {
            if (current instanceof MethodInsnNode) {
                MethodInsnNode call = (MethodInsnNode) current;
                if (call.owner.equals("java/io/DataOutputStream")
                        && call.name.equals("writeInt") && count++ == 0) {
                    InsnList send = new InsnList();
                    send.add(new VarInsnNode(ALOAD, userName));
                    send.add(new MethodInsnNode(INVOKESTATIC, HELPER, "clientSend",
                            "(Ljava/lang/String;)V", false));
                    method.instructions.insertBefore(current, send);
                }
            }
        }
        if (count == 0) throw new IllegalStateException("no SASL preamble write");
    }

    private static void patchServerReceive(MethodNode method) {
        int count = 0;
        for (AbstractInsnNode current = method.instructions.getFirst();
             current != null; current = current.getNext()) {
            if (current instanceof MethodInsnNode) {
                MethodInsnNode call = (MethodInsnNode) current;
                if (call.owner.equals("java/lang/String") && call.name.equals("split")
                        && count++ == 0) {
                    InsnList receive = new InsnList();
                    receive.add(new VarInsnNode(ALOAD, 1));
                    receive.add(new MethodInsnNode(INVOKESTATIC, HELPER,
                            "serverReceive", "(Ljava/lang/String;)V", false));
                    method.instructions.insertBefore(current, receive);
                }
            }
        }
        if (count != 1) throw new IllegalStateException("expected one SASL username split, found " + count);
    }

    private static void addFinally(MethodNode method, String helperMethod) {
        int thrown = method.maxLocals++;
        LabelNode start = new LabelNode();
        LabelNode end = new LabelNode();
        LabelNode handler = new LabelNode();
        method.instructions.insertBefore(method.instructions.getFirst(), start);
        for (AbstractInsnNode current = method.instructions.getFirst();
             current != null; ) {
            AbstractInsnNode next = current.getNext();
            int opcode = current.getOpcode();
            if (opcode == ARETURN || opcode == IRETURN || opcode == LRETURN
                    || opcode == FRETURN || opcode == DRETURN || opcode == RETURN) {
                InsnList leave = new InsnList();
                leave.add(new MethodInsnNode(INVOKESTATIC, HELPER, helperMethod,
                        "()V", false));
                method.instructions.insertBefore(current, leave);
            }
            current = next;
        }
        method.instructions.add(end);
        method.instructions.add(handler);
        method.instructions.add(new VarInsnNode(ASTORE, thrown));
        method.instructions.add(new MethodInsnNode(INVOKESTATIC, HELPER,
                helperMethod, "()V", false));
        method.instructions.add(new VarInsnNode(ALOAD, thrown));
        method.instructions.add(new InsnNode(ATHROW));
        method.tryCatchBlocks.add(new TryCatchBlockNode(start, end, handler,
                "java/lang/Throwable"));
    }
}
