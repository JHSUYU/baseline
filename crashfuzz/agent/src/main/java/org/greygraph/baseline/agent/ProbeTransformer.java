package org.greygraph.baseline.agent;

import java.lang.instrument.ClassFileTransformer;
import java.io.IOException;
import java.io.InputStream;
import java.security.ProtectionDomain;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.Set;

import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.Type;
import org.objectweb.asm.commons.AdviceAdapter;
import org.objectweb.asm.commons.Method;

/** Injects generic event hooks into configured application packages. */
final class ProbeTransformer implements ClassFileTransformer {
    private static final Type HOOK = Type.getType(Hook.class);
    private static final Type HBASE_RPC = Type.getType(HBase248RpcHooks.class);
    private static final Type HDFS_TRANSFER = Type.getType(HdfsDataTransferHooks.class);
    private static final Type HADOOP_RPC = Type.getType(HadoopRpcHooks.class);
    private static final Method ENTER = new Method("enter",
            "(Ljava/lang/String;Ljava/lang/Object;)J");
    private static final Method ENTER_TASK = new Method("enterTask",
            "(Ljava/lang/String;Ljava/lang/Object;)J");
    private static final Method EXIT = new Method("exit", "(J)V");
    private static final Method FIELD_READ = new Method("fieldRead",
            "(Ljava/lang/String;Ljava/lang/Object;)V");
    private static final Method FIELD_WRITE = new Method("fieldWrite",
            "(Ljava/lang/String;Ljava/lang/Object;)V");
    private static final Method BRANCH = new Method("branch",
            "(Ljava/lang/String;Z)V");
    private static final Method POINT = new Method("point",
            "(Ljava/lang/String;Ljava/lang/String;)V");
    private static final Method THROWING = new Method("throwing",
            "(Ljava/lang/String;Ljava/lang/Throwable;)V");
    private static final Method TARGET = new Method("target",
            "(Ljava/lang/String;Z)V");
    private static final Method CALL_THROWN = new Method("callThrown",
            "(Ljava/lang/String;Ljava/lang/Throwable;)V");
    private static final Method ASYNC_SUBMIT = new Method("asyncSubmit",
            "(Ljava/lang/Object;)V");
    private static final Method RPC_REQUEST_SEND = new Method("requestSend",
            "(Ljava/lang/Object;Ljava/lang/Object;)V");
    private static final Method RPC_REQUEST_RECV = new Method("requestReceive",
            "(ILjava/lang/Object;)V");
    private static final Method RPC_RESPONSE_SEND = new Method("responseSend",
            "(Ljava/lang/Object;)V");
    private static final Method RPC_RESPONSE_RECV = new Method("responseReceive",
            "(ILjava/lang/Object;)V");
    private static final Method HDFS_SOCKET_SEND = new Method("socketSend", "(Ljava/lang/Object;)V");
    private static final Method HDFS_PEER_SEND = new Method("peerSend", "(Ljava/lang/Object;)V");
    private static final Method HDFS_SERVER_RECEIVE = new Method("serverReceive", "(Ljava/lang/Object;)V");
    private static final Method HDFS_SERVER_RESPONSE = new Method("serverResponse", "(Ljava/lang/Object;)V");
    private static final Method HDFS_SOCKET_RESPONSE = new Method("socketResponse", "(Ljava/lang/Object;)V");
    private static final Method HDFS_PEER_RESPONSE = new Method("peerResponse", "(Ljava/lang/Object;)V");
    private static final Method HADOOP_REQUEST_SEND = new Method("requestSend", "(Ljava/lang/Object;Ljava/lang/Object;)V");
    private static final Method HADOOP_REQUEST_RECV = new Method("requestReceive", "(Ljava/lang/Object;)V");
    private static final Method HADOOP_RESPONSE_SEND = new Method("responseSend", "(Ljava/lang/Object;)V");
    private static final Method HADOOP_RESPONSE_RECV = new Method("responseReceive", "(ILjava/lang/Object;)V");
    private static final Method ASYNC_RECEIVE = new Method("asyncReceive", "(Ljava/lang/Object;)V");

    private final List<String> includes = new ArrayList<String>();
    private final List<String> exactClasses = new ArrayList<String>();
    private final List<String> methodRules = new ArrayList<String>();
    private final List<String> ioRules = new ArrayList<String>();
    private final boolean traceFields;
    private final boolean traceBranches;
    private final String targetGuard;
    private final String targetCall;
    private final boolean debug;
    private final boolean hbase248Rpc;
    private final boolean hdfsDataTransfer;
    private final boolean hadoopRpc;

    ProbeTransformer(Properties config) {
        for (String prefix : config.getProperty("include.prefixes", "").split(",")) {
            String normalized = prefix.trim().replace('.', '/');
            if (!normalized.isEmpty()) includes.add(normalized);
        }
        for (String name : config.getProperty("include.classes", "").split(",")) {
            String normalized = name.trim().replace('.', '/');
            if (!normalized.isEmpty()) exactClasses.add(normalized);
        }
        if (includes.isEmpty() && exactClasses.isEmpty()) {
            throw new IllegalArgumentException(
                    "include.prefixes or include.classes is required");
        }
        for (String rule : config.getProperty("method.rules", "").split(",")) {
            String normalized = rule.trim().replace('.', '/');
            if (!normalized.isEmpty()) methodRules.add(normalized);
        }
        for (String rule : config.getProperty("io.rules", "").split(",")) {
            String normalized = rule.trim().replace('.', '/');
            if (!normalized.isEmpty()) ioRules.add(normalized);
        }
        traceFields = Boolean.parseBoolean(
                config.getProperty("trace.fields", "true"));
        traceBranches = Boolean.parseBoolean(
                config.getProperty("trace.branches", "false"));
        targetGuard = config.getProperty("target.guard", "").trim();
        targetCall = config.getProperty("target.call", "").trim();
        debug = Boolean.parseBoolean(config.getProperty("agent.debug", "false"));
        hbase248Rpc = Boolean.parseBoolean(
                config.getProperty("adapter.hbase248.rpc", "false"));
        hdfsDataTransfer = Boolean.parseBoolean(
                config.getProperty("adapter.hdfs.datatransfer", "false"));
        hadoopRpc = Boolean.parseBoolean(
                config.getProperty("adapter.hadoop.rpc", "false"));
    }

    @Override
    public byte[] transform(ClassLoader loader, String className,
                            Class<?> classBeingRedefined,
                            ProtectionDomain protectionDomain,
                            byte[] bytes) {
        if (className == null || !included(className)) return null;
        try {
            if (debug) System.err.println("adhoc-crashfuzz: instrumenting " + className);
            ClassReader reader = new ClassReader(bytes);
            ClassWriter writer = new LoaderClassWriter(reader,
                    ClassWriter.COMPUTE_FRAMES | ClassWriter.COMPUTE_MAXS,
                    loader);
            reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
                @Override
                public MethodVisitor visitMethod(int access, String name,
                                                 String descriptor,
                                                 String signature,
                                                 String[] exceptions) {
                    MethodVisitor method = super.visitMethod(access, name,
                            descriptor, signature, exceptions);
                    if (method == null || (access & (Opcodes.ACC_ABSTRACT
                            | Opcodes.ACC_NATIVE)) != 0
                            || !allowedMethod(className, name)) return method;
                    return new ProbeMethod(method, access, className, name,
                            descriptor);
                }
            }, ClassReader.EXPAND_FRAMES);
            return writer.toByteArray();
        } catch (Throwable failure) {
            System.err.println("adhoc-crashfuzz: instrumentation failed for "
                    + className);
            failure.printStackTrace(System.err);
            return null;
        }
    }

    private boolean included(String name) {
        if (name.startsWith("org/greygraph/baseline/agent/")
                || name.startsWith("org/objectweb/asm/")) return false;
        for (String prefix : includes) {
            if (name.startsWith(prefix)) return true;
        }
        return exactClasses.contains(name);
    }

    private boolean allowedMethod(String owner, String name) {
        if (methodRules.isEmpty()) return true;
        String at = owner + "#" + name;
        for (String rule : methodRules) {
            if (rule.endsWith("*") ? at.startsWith(rule.substring(0,
                    rule.length() - 1)) : at.equals(rule)) return true;
        }
        return false;
    }

    private boolean ioCall(String owner, String name) {
        String at = owner + "#" + name;
        for (String rule : ioRules) {
            if (rule.endsWith("*") ? at.startsWith(rule.substring(0,
                    rule.length() - 1)) : at.equals(rule)) return true;
        }
        return false;
    }

    private static boolean conditional(int opcode) {
        return (opcode >= Opcodes.IFEQ && opcode <= Opcodes.IF_ACMPNE)
                || opcode == Opcodes.IFNULL || opcode == Opcodes.IFNONNULL;
    }

    private static final class LoaderClassWriter extends ClassWriter {
        private final ClassLoader loader;
        private final Map<String, ClassInfo> hierarchy = new HashMap<String, ClassInfo>();

        private static final class ClassInfo {
            final String parent;
            final String[] interfaces;
            final boolean interfaceType;

            ClassInfo(String parent, String[] interfaces, boolean interfaceType) {
                this.parent = parent;
                this.interfaces = interfaces;
                this.interfaceType = interfaceType;
            }
        }

        LoaderClassWriter(ClassReader reader, int flags, ClassLoader loader) {
            super(reader, flags);
            this.loader = loader;
        }

        @Override
        protected String getCommonSuperClass(String left, String right) {
            if (left.equals(right)) return left;
            if (left.startsWith("[") || right.startsWith("[")) {
                if (left.startsWith("[") && right.startsWith("[")) {
                    Type a = Type.getType(left);
                    Type b = Type.getType(right);
                    if (a.getDimensions() == b.getDimensions()
                            && a.getElementType().getSort() == Type.OBJECT
                            && b.getElementType().getSort() == Type.OBJECT) {
                        StringBuilder result = new StringBuilder();
                        for (int i = 0; i < a.getDimensions(); i++) result.append('[');
                        return result.append('L').append(getCommonSuperClass(
                                a.getElementType().getInternalName(),
                                b.getElementType().getInternalName()))
                                .append(';').toString();
                    }
                }
                return "java/lang/Object";
            }
            if (assignable(left, right)) return left;
            if (assignable(right, left)) return right;
            ClassInfo a = classInfo(left);
            ClassInfo b = classInfo(right);
            if (a == null || b == null || a.interfaceType || b.interfaceType)
                return "java/lang/Object";
            String parent = a.parent;
            while (parent != null) {
                if (assignable(parent, right)) return parent;
                ClassInfo info = classInfo(parent);
                parent = info == null ? null : info.parent;
            }
            return "java/lang/Object";
        }

        private boolean assignable(String ancestor, String child) {
            Deque<String> pending = new ArrayDeque<String>();
            Set<String> visited = new HashSet<String>();
            pending.add(child);
            while (!pending.isEmpty()) {
                String current = pending.removeFirst();
                if (ancestor.equals(current)) return true;
                if (!visited.add(current)) continue;
                ClassInfo info = classInfo(current);
                if (info == null) continue;
                if (info.parent != null) pending.addLast(info.parent);
                for (String parent : info.interfaces) pending.addLast(parent);
            }
            return false;
        }

        private ClassInfo classInfo(String name) {
            if (hierarchy.containsKey(name)) return hierarchy.get(name);
            ClassLoader lookup = loader == null
                    ? ClassLoader.getSystemClassLoader() : loader;
            try (InputStream stream = lookup.getResourceAsStream(name + ".class")) {
                if (stream == null) {
                    hierarchy.put(name, null);
                    return null;
                }
                ClassReader reader = new ClassReader(stream);
                ClassInfo info = new ClassInfo(reader.getSuperName(),
                        reader.getInterfaces(),
                        (reader.getAccess() & Opcodes.ACC_INTERFACE) != 0);
                hierarchy.put(name, info);
                return info;
            } catch (IOException | RuntimeException unavailable) {
                hierarchy.put(name, null);
                return null;
            }
        }
    }

    private final class ProbeMethod extends AdviceAdapter {
        private final String methodSite;
        private final String owner;
        private final String methodName;
        private final String descriptor;
        private final boolean isStatic;
        private int spanLocal;
        private int line = -1;
        private int branchIndex;
        private int callIndex;
        private boolean entered;
        private final Label start = new Label();
        private final Label end = new Label();
        private final Label caught = new Label();

        ProbeMethod(MethodVisitor next, int access, String owner,
                    String name, String descriptor) {
            super(Opcodes.ASM9, next, access, name, descriptor);
            this.owner = owner;
            this.methodName = name;
            this.descriptor = descriptor;
            this.methodSite = owner + "#" + name + descriptor;
            this.isStatic = (access & Opcodes.ACC_STATIC) != 0;
        }

        @Override
        protected void onMethodEnter() {
            spanLocal = newLocal(Type.LONG_TYPE);
            push(methodSite);
            boolean procedureWorker = hbase248Rpc
                    && owner.equals("org/apache/hadoop/hbase/procedure2/ProcedureExecutor")
                    && methodName.equals("executeProcedure");
            if (procedureWorker) loadArg(0);
            else if (isStatic) visitInsn(ACONST_NULL);
            else loadThis();
            invokeStatic(HOOK, procedureWorker ? ENTER_TASK : ENTER);
            storeLocal(spanLocal);
            mark(start);
            entered = true;
            if (hbase248Rpc
                    && owner.equals("org/apache/hadoop/hbase/ipc/NettyRpcDuplexHandler")
                    && methodName.equals("writeRequest")) {
                loadArg(0);
                loadArg(1);
                invokeStatic(HBASE_RPC, RPC_REQUEST_SEND);
            }
            if (hdfsDataTransfer && owner.equals(
                    "org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferClient")) {
                int args = Type.getArgumentTypes(descriptor).length;
                if (methodName.equals("newSocketSend")
                        || (methodName.equals("socketSend") && args == 7)) {
                    loadArg(0);
                    invokeStatic(HDFS_TRANSFER, HDFS_SOCKET_SEND);
                } else if (methodName.equals("peerSend")) {
                    loadArg(0);
                    invokeStatic(HDFS_TRANSFER, HDFS_PEER_SEND);
                }
            } else if (hdfsDataTransfer && owner.equals(
                    "org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferServer")
                    && methodName.equals("receive")) {
                loadArg(0);
                invokeStatic(HDFS_TRANSFER, HDFS_SERVER_RECEIVE);
            }
            if (hadoopRpc && owner.equals("org/apache/hadoop/ipc/Client$Connection")
                    && methodName.equals("sendRpcRequest")) {
                loadThis();
                loadArg(0);
                invokeStatic(HADOOP_RPC, HADOOP_REQUEST_SEND);
            } else if (hadoopRpc && owner.equals("org/apache/hadoop/ipc/Server$Connection")
                    && methodName.equals("processRpcRequest")) {
                loadArg(0);
                invokeStatic(HADOOP_RPC, HADOOP_REQUEST_RECV);
            } else if (hadoopRpc && owner.equals("org/apache/hadoop/ipc/Server$Responder")
                    && methodName.equals("doRespond")) {
                loadArg(0);
                invokeStatic(HADOOP_RPC, HADOOP_RESPONSE_SEND);
            } else if (hadoopRpc && owner.equals("org/apache/hadoop/ipc/Client$Call")
                    && methodName.equals("setRpcResponse")) {
                loadThis();
                invokeStatic(HOOK, ASYNC_SUBMIT);
            }
            if (hbase248Rpc
                    && owner.equals("org/apache/hadoop/hbase/procedure2/ProcedureExecutor")
                    && methodName.equals("submitProcedure")
                    && Type.getArgumentTypes(descriptor).length == 2) {
                loadArg(0);
                invokeStatic(HOOK, ASYNC_SUBMIT);
            }
        }

        @Override
        protected void onMethodExit(int opcode) {
            if (opcode == ATHROW) {
                int throwable = newLocal(Type.getType(Throwable.class));
                dup();
                storeLocal(throwable);
                push(methodSite + "#L" + line);
                loadLocal(throwable);
                invokeStatic(HOOK, THROWING);
                return;  // A local catch can continue this activation.
            }
            if (hbase248Rpc && opcode == RETURN
                    && owner.equals("org/apache/hadoop/hbase/ipc/NettyServerCall")
                    && methodName.equals("sendResponseIfReady")) {
                loadThis();
                invokeStatic(HBASE_RPC, RPC_RESPONSE_SEND);
            }
            if (hdfsDataTransfer && opcode == ARETURN) {
                if (owner.equals("org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferServer")
                        && methodName.equals("receive")) {
                    loadArg(0);
                    invokeStatic(HDFS_TRANSFER, HDFS_SERVER_RESPONSE);
                } else if (owner.equals("org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferClient")) {
                    int args = Type.getArgumentTypes(descriptor).length;
                    if (methodName.equals("newSocketSend")
                            || (methodName.equals("socketSend") && args == 7)) {
                        loadArg(0);
                        invokeStatic(HDFS_TRANSFER, HDFS_SOCKET_RESPONSE);
                    } else if (methodName.equals("peerSend")) {
                        loadArg(0);
                        invokeStatic(HDFS_TRANSFER, HDFS_PEER_RESPONSE);
                    }
                }
            }
            if (hadoopRpc && opcode == ARETURN
                    && owner.equals("org/apache/hadoop/ipc/Client")
                    && methodName.equals("getRpcResponse")) {
                loadArg(0);
                invokeStatic(HOOK, ASYNC_RECEIVE);
            }
            if (hdfsDataTransfer && opcode == RETURN
                    && owner.equals("org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager")
                    && methodName.equals("addKeys")) {
                push("org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager#allKeys:Ljava/util/Map;");
                loadThis();
                invokeStatic(HOOK, FIELD_WRITE);
            }
            loadLocal(spanLocal);
            invokeStatic(HOOK, EXIT);
        }

        @Override
        public void visitMaxs(int maxStack, int maxLocals) {
            mark(end);
            visitTryCatchBlock(start, end, caught, null);
            mark(caught);
            int throwable = newLocal(Type.getType(Throwable.class));
            storeLocal(throwable);
            loadLocal(spanLocal);
            invokeStatic(HOOK, EXIT);
            loadLocal(throwable);
            mv.visitInsn(ATHROW);
            super.visitMaxs(maxStack, maxLocals);
        }

        @Override
        public void visitLineNumber(int lineNumber, Label at) {
            line = lineNumber;
            super.visitLineNumber(lineNumber, at);
        }

        @Override
        public void visitFieldInsn(int opcode, String fieldOwner,
                                   String name, String fieldDesc) {
            if (!entered || !traceFields || !included(fieldOwner)) {
                super.visitFieldInsn(opcode, fieldOwner, name, fieldDesc);
                return;
            }
            String site = fieldOwner + "#" + name + ":" + fieldDesc;
            Type valueType = Type.getType(fieldDesc);
            if (opcode == GETFIELD) {
                int receiver = newLocal(Type.getType(Object.class));
                int value = newLocal(valueType);
                storeLocal(receiver);
                loadLocal(receiver);
                super.visitFieldInsn(opcode, fieldOwner, name, fieldDesc);
                storeLocal(value);
                push(site);
                loadLocal(receiver);
                invokeStatic(HOOK, FIELD_READ);
                loadLocal(value);
            } else if (opcode == GETSTATIC) {
                int value = newLocal(valueType);
                super.visitFieldInsn(opcode, fieldOwner, name, fieldDesc);
                storeLocal(value);
                push(site);
                visitInsn(ACONST_NULL);
                invokeStatic(HOOK, FIELD_READ);
                loadLocal(value);
            } else if (opcode == PUTFIELD) {
                int value = newLocal(valueType);
                int receiver = newLocal(Type.getType(Object.class));
                storeLocal(value);
                storeLocal(receiver);
                loadLocal(receiver);
                loadLocal(value);
                super.visitFieldInsn(opcode, fieldOwner, name, fieldDesc);
                push(site);
                loadLocal(receiver);
                invokeStatic(HOOK, FIELD_WRITE);
            } else if (opcode == PUTSTATIC) {
                int value = newLocal(valueType);
                storeLocal(value);
                loadLocal(value);
                super.visitFieldInsn(opcode, fieldOwner, name, fieldDesc);
                push(site);
                visitInsn(ACONST_NULL);
                invokeStatic(HOOK, FIELD_WRITE);
            } else {
                super.visitFieldInsn(opcode, fieldOwner, name, fieldDesc);
            }
        }

        @Override
        public void visitJumpInsn(int opcode, Label destination) {
            if (!entered) {
                super.visitJumpInsn(opcode, destination);
                return;
            }
            if (!conditional(opcode)) {
                super.visitJumpInsn(opcode, destination);
                return;
            }
            branchIndex++;
            String site = methodSite + "#B" + branchIndex;
            if (!traceBranches && !site.equals(targetGuard)) {
                super.visitJumpInsn(opcode, destination);
                return;
            }
            Label taken = new Label();
            Label continued = new Label();
            super.visitJumpInsn(opcode, taken);
            push(site);
            push(false);
            invokeStatic(HOOK, BRANCH);
            super.visitJumpInsn(GOTO, continued);
            mark(taken);
            push(site);
            push(true);
            invokeStatic(HOOK, BRANCH);
            super.visitJumpInsn(GOTO, destination);
            mark(continued);
        }

        @Override
        public void visitMethodInsn(int opcode, String calleeOwner,
                                    String name, String callDesc,
                                    boolean isInterface) {
            if (!entered) {
                super.visitMethodInsn(opcode, calleeOwner, name, callDesc,
                                      isInterface);
                return;
            }
            callIndex++;
            String site = methodSite + "#I" + callIndex + "->"
                    + calleeOwner + "#" + name + callDesc;
            String callSite = methodSite + "#L" + line + "->"
                    + calleeOwner + "#" + name;
            boolean selectedCall = callSite.equals(targetCall);
            boolean io = ioCall(calleeOwner, name);
            if (io) {
                push(site);
                push("BEFORE");
                invokeStatic(HOOK, POINT);
            }
            boolean oneTask = (opcode != INVOKESTATIC
                    && (name.equals("execute") || name.equals("submit"))
                    && (callDesc.startsWith("(Ljava/lang/Runnable;")
                        || callDesc.startsWith("(Ljava/util/concurrent/Callable;"))
                    && Type.getArgumentTypes(callDesc).length == 1);
            boolean threadStart = (opcode != INVOKESTATIC
                    && calleeOwner.equals("java/lang/Thread")
                    && name.equals("start") && callDesc.equals("()V"));
            boolean hbaseDispatch = hbase248Rpc
                    && owner.equals("org/apache/hadoop/hbase/ipc/ServerRpcConnection")
                    && methodName.equals("processRequest")
                    && name.equals("dispatch")
                    && callDesc.startsWith("(Lorg/apache/hadoop/hbase/ipc/CallRunner;)");
            boolean hadoopDispatch = hadoopRpc
                    && owner.equals("org/apache/hadoop/ipc/Server$Connection")
                    && methodName.equals("processRpcRequest")
                    && (name.equals("internalQueueCall")
                        || name.equals("access$3600"))
                    && callDesc.contains("Lorg/apache/hadoop/ipc/Server$Call;)V");
            if (oneTask || threadStart || hbaseDispatch || hadoopDispatch) {
                dup();
                invokeStatic(HOOK, ASYNC_SUBMIT);
            }
            if (selectedCall) {
                push(callSite);
                push(false);
                invokeStatic(HOOK, TARGET);
                Label callStart = new Label();
                Label callEnd = new Label();
                Label callFailed = new Label();
                Label callDone = new Label();
                mark(callStart);
                super.visitMethodInsn(opcode, calleeOwner, name, callDesc,
                                      isInterface);
                mark(callEnd);
                goTo(callDone);
                visitTryCatchBlock(callStart, callEnd, callFailed, null);
                mark(callFailed);
                int throwable = newLocal(Type.getType(Throwable.class));
                storeLocal(throwable);
                push(callSite);
                loadLocal(throwable);
                invokeStatic(HOOK, CALL_THROWN);
                loadLocal(throwable);
                throwException();
                mark(callDone);
            } else {
                super.visitMethodInsn(opcode, calleeOwner, name, callDesc,
                                      isInterface);
            }
            if (hbase248Rpc && name.equals("getCallId")
                    && callDesc.equals("()I")) {
                if (owner.equals("org/apache/hadoop/hbase/ipc/ServerRpcConnection")
                        && methodName.equals("processRequest")) {
                    dup();
                    loadThis();
                    invokeStatic(HBASE_RPC, RPC_REQUEST_RECV);
                } else if (owner.equals("org/apache/hadoop/hbase/ipc/NettyRpcDuplexHandler")
                        && methodName.equals("readResponse")) {
                    dup();
                    loadArg(0);
                    invokeStatic(HBASE_RPC, RPC_RESPONSE_RECV);
                }
            }
            if (hadoopRpc && owner.equals("org/apache/hadoop/ipc/Client$Connection")
                    && methodName.equals("receiveRpcResponse")
                    && name.equals("getCallId") && callDesc.equals("()I")) {
                dup();
                loadThis();
                invokeStatic(HADOOP_RPC, HADOOP_RESPONSE_RECV);
            }
            if (io) {
                push(site);
                push("AFTER");
                invokeStatic(HOOK, POINT);
            }
        }
    }
}
