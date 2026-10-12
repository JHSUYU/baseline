package edu.uva.liftlab.mallory.solr;

import java.lang.instrument.ClassFileTransformer;
import java.security.ProtectionDomain;
import java.util.ArrayList;
import java.util.List;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.Type;

/** Selective Solr 8.11.4 handoff hooks. No Solr classes are linked by this adapter. */
public final class SolrTransformer implements ClassFileTransformer {
  private static final String HOOKS = "edu/uva/liftlab/mallory/solr/SolrHooks";
  private static final String ZK = "org/apache/solr/cloud/ZkController";
  private static final String FILTER = "org/apache/solr/servlet/SolrDispatchFilter";
  private static final String HTTP2 = "org/apache/solr/client/solrj/impl/Http2SolrClient";
  private static final String HTTP1 = "org/apache/solr/client/solrj/impl/HttpSolrClient";
  private static final String CLIENT_STATE = "org/apache/solr/client/solrj/impl/BaseHttpClusterStateProvider";
  private static final String CLIENT_ZK = "org/apache/solr/client/solrj/impl/ZkClientClusterStateProvider";
  private static final String STATE_READER = "org/apache/solr/common/cloud/ZkStateReader";
  private static final String STATE_WATCHER = "org/apache/solr/common/cloud/ZkStateReader$StateWatcher";
  private static final String COLLECTIONS_HANDLER = "org/apache/solr/handler/admin/CollectionsHandler";
  private static final String SLICE = "org/apache/solr/common/cloud/Slice";
  private static final String OVERSEER = "org/apache/solr/cloud/api/collections/OverseerCollectionMessageHandler";
  private static final String OVERSEER_TASK_PROCESSOR = "org/apache/solr/cloud/OverseerTaskProcessor";
  private static final String ALIASES = "org/apache/solr/common/cloud/ZkStateReader$AliasesManager";
  private static final String ZK_WATCH_DISPATCH = "org/apache/solr/common/cloud/SolrZkClient$ProcessWatchWithExecutor";
  private static final String POOL = "org/apache/solr/common/util/ExecutorUtil$MDCAwareThreadPoolExecutor";
  private static final String SHARD_REQUESTOR = "org/apache/solr/handler/component/ShardRequestor";
  private static final String HTTP_SHARD_HANDLER = "org/apache/solr/handler/component/HttpShardHandler";

  @Override
  public byte[] transform(ClassLoader loader, String className, Class<?> classBeingRedefined,
      ProtectionDomain protectionDomain, byte[] classfileBuffer) {
    if (!ZK.equals(className) && !FILTER.equals(className) && !CLIENT_STATE.equals(className)
        && !CLIENT_ZK.equals(className)
        && !OVERSEER.equals(className) && !OVERSEER_TASK_PROCESSOR.equals(className)
        && !ALIASES.equals(className) && !ZK_WATCH_DISPATCH.equals(className)
        && !STATE_WATCHER.equals(className) && !STATE_READER.equals(className)
        && !COLLECTIONS_HANDLER.equals(className)
        && !HTTP1.equals(className) && !HTTP2.equals(className) && !POOL.equals(className)
        && !SHARD_REQUESTOR.equals(className) && !HTTP_SHARD_HANDLER.equals(className)) return null;
    try {
      ClassReader reader = new ClassReader(classfileBuffer);
      ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_MAXS);
      ClassVisitor visitor = new ClassVisitor(Opcodes.ASM9, writer) {
        @Override public MethodVisitor visitMethod(int access, String name, String descriptor,
            String signature, String[] exceptions) {
          MethodVisitor method = super.visitMethod(access, name, descriptor, signature, exceptions);
          if (method == null || (access & (Opcodes.ACC_ABSTRACT | Opcodes.ACC_NATIVE)) != 0) return method;
          if (ZK.equals(className)) {
            if ("<init>".equals(name)) return constructor(method, "registerController");
            if ("register".equals(name) && descriptor.startsWith("(Ljava/lang/String;"))
              return scoped(method, "beginController", "endController", false,
                  className, access, descriptor);
          }
          if (FILTER.equals(className) && "doFilter".equals(name)
              && descriptor.startsWith("(Ljavax/servlet/ServletRequest;Ljavax/servlet/ServletResponse;Ljavax/servlet/FilterChain;Z)"))
            return scoped(method, "beginHttp", "endHttp", true,
                className, access, descriptor);
          if (CLIENT_STATE.equals(className) && "getAliases".equals(name)
              && "(Z)Ljava/util/Map;".equals(descriptor))
            return scoped(method, "beginClient", "endClient", false,
                className, access, descriptor);
          if (CLIENT_ZK.equals(className)) {
            if ("<init>".equals(name)) return constructor(method, "registerClientProvider");
            if ("getZkStateReader".equals(name)) return clientReader(method);
          }
          if (STATE_READER.equals(className) && "fetchCollectionState".equals(name)
              && "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Ljava/lang/String;)Lorg/apache/solr/common/cloud/DocCollection;".equals(descriptor))
            return qualifiedStateRead(method);
          if (OVERSEER.equals(className) && "processMessage".equals(name))
            return scoped(method, "beginOverseer", "endOverseer", false,
                className, access, descriptor);
          if (OVERSEER_TASK_PROCESSOR.equals(className) && "run".equals(name)
              && "()V".equals(descriptor) && (access & Opcodes.ACC_STATIC) == 0)
            return scoped(method, "beginOverseerTaskProcessor", "endOverseerTaskProcessor",
                false, className, access, descriptor);
          if (ALIASES.equals(className) && ("setIfNewer".equals(name)
              || "process".equals(name) || "update".equals(name)
              || "applyModificationAndExportToZk".equals(name)))
            return scoped(method, "beginAliasesManager", "endAliasesManager", false,
                className, access, descriptor);
          if (ZK_WATCH_DISPATCH.equals(className) && "process".equals(name)
              && "(Lorg/apache/zookeeper/WatchedEvent;)V".equals(descriptor))
            return scoped(method, "beginZkWatchDispatch", "endZkWatchDispatch", false,
                className, access, descriptor);
          if (STATE_WATCHER.equals(className) && "refreshAndWatch".equals(name)
              && "(Lorg/apache/zookeeper/Watcher$Event$EventType;)V".equals(descriptor))
            return scoped(method, "beginStateWatcher", "endStateWatcher", false,
                className, access, descriptor);
          if (STATE_WATCHER.equals(className) && "refreshAndWatchChildren".equals(name)
              && "()V".equals(descriptor))
            return qualifiedStateChildrenRead(method);
          if (COLLECTIONS_HANDLER.equals(className) && "forceLeaderElection".equals(name)
              && "(Lorg/apache/solr/request/SolrQueryRequest;Lorg/apache/solr/handler/admin/CollectionsHandler;)V".equals(descriptor))
            return forceLeaderOperand(method);
          if ((HTTP2.equals(className) || HTTP1.equals(className)) && "<init>".equals(name))
            return constructor(method, "registerHttpClient");
          if ((HTTP2.equals(className) || HTTP1.equals(className)) && "request".equals(name)
              && (access & Opcodes.ACC_STATIC) == 0)
            return scoped(method, "beginHttpClient", "endHttpClient", false,
                className, access, descriptor);
          if (HTTP1.equals(className) && "executeMethod".equals(name)
              && (access & Opcodes.ACC_STATIC) == 0)
            return scoped(method, "beginHttpClient", "endHttpClient", false,
                className, access, descriptor);
          if (HTTP2.equals(className) && "createRequest".equals(name)) return outbound(method);
          if (HTTP1.equals(className) && "createMethod".equals(name)) return outbound(method);
          if (POOL.equals(className) && "execute".equals(name)
              && "(Ljava/lang/Runnable;)V".equals(descriptor)) return executor(method);
          if (SHARD_REQUESTOR.equals(className) && "call".equals(name)
              && "()Lorg/apache/solr/handler/component/ShardResponse;".equals(descriptor))
            return shardResponseCompletion(method);
          if (HTTP_SHARD_HANDLER.equals(className) && "take".equals(name)
              && "(Z)Lorg/apache/solr/handler/component/ShardResponse;".equals(descriptor))
            return shardResponseJoin(method);
          return method;
        }
      };
      reader.accept(visitor, 0);
      return writer.toByteArray();
    } catch (Throwable failure) {
      System.err.println("Mallory Solr adapter failed to instrument " + className + ": " + failure);
      return null;
    }
  }

  private static MethodVisitor constructor(MethodVisitor method, String hook) {
    return new MethodVisitor(Opcodes.ASM9, method) {
      @Override public void visitMethodInsn(int opcode, String owner, String name,
          String descriptor, boolean isInterface) {
        if ("registerController".equals(hook) && ZK.equals(owner) && "init".equals(name)) {
          super.visitVarInsn(Opcodes.ALOAD, 0);
          super.visitMethodInsn(Opcodes.INVOKESTATIC, HOOKS, hook,
              "(Ljava/lang/Object;)V", false);
        }
        super.visitMethodInsn(opcode, owner, name, descriptor, isInterface);
      }
      @Override public void visitInsn(int opcode) {
        if (opcode == Opcodes.RETURN) {
          super.visitVarInsn(Opcodes.ALOAD, 0);
          super.visitMethodInsn(Opcodes.INVOKESTATIC, HOOKS, hook,
              "(Ljava/lang/Object;)V", false);
        }
        super.visitInsn(opcode);
      }
    };
  }

  private static MethodVisitor clientReader(MethodVisitor method) {
    return new MethodVisitor(Opcodes.ASM9, method) {
      @Override public void visitMethodInsn(int opcode, String owner, String name,
          String descriptor, boolean isInterface) {
        if (STATE_READER.equals(owner) && "createClusterStateWatchersAndUpdate".equals(name)) {
          super.visitInsn(Opcodes.DUP);
          super.visitMethodInsn(Opcodes.INVOKESTATIC, HOOKS, "registerClientReader",
              "(Ljava/lang/Object;)V", false);
        }
        super.visitMethodInsn(opcode, owner, name, descriptor, isInterface);
      }
      @Override public void visitInsn(int opcode) {
        if (opcode == Opcodes.ARETURN) {
          super.visitInsn(Opcodes.DUP);
          super.visitMethodInsn(Opcodes.INVOKESTATIC, HOOKS, "registerClientReader",
              "(Ljava/lang/Object;)V", false);
        }
        super.visitInsn(opcode);
      }
    };
  }

  private static MethodVisitor scoped(MethodVisitor method, String begin, String end,
      boolean requestArg, String owner, int access, String descriptor) {
    final Label start = new Label();
    final Label finish = new Label();
    final Label handler = new Label();
    final Object[] entryLocals = entryLocals(owner, access, descriptor);
    return new MethodVisitor(Opcodes.ASM9, method) {
      @Override public void visitCode() {
        super.visitCode();
        super.visitVarInsn(Opcodes.ALOAD, 0);
        if (requestArg) {
          super.visitVarInsn(Opcodes.ALOAD, 1);
          super.visitVarInsn(Opcodes.ILOAD, 4);
        }
        super.visitMethodInsn(Opcodes.INVOKESTATIC, HOOKS, begin,
            requestArg ? "(Ljava/lang/Object;Ljava/lang/Object;Z)V" : "(Ljava/lang/Object;)V", false);
        super.visitLabel(start);
      }
      @Override public void visitInsn(int opcode) {
        if (opcode >= Opcodes.IRETURN && opcode <= Opcodes.RETURN)
          super.visitMethodInsn(Opcodes.INVOKESTATIC, HOOKS, end, "()V", false);
        super.visitInsn(opcode);
      }
      @Override public void visitMaxs(int maxStack, int maxLocals) {
        // Append after Solr's handlers and the generic region handler, so they run first.
        super.visitTryCatchBlock(start, finish, handler, null);
        super.visitLabel(finish);
        super.visitLabel(handler);
        super.visitFrame(Opcodes.F_FULL, entryLocals.length, entryLocals,
            1, new Object[] {"java/lang/Throwable"});
        super.visitMethodInsn(Opcodes.INVOKESTATIC, HOOKS, end, "()V", false);
        super.visitInsn(Opcodes.ATHROW);
        super.visitMaxs(maxStack, maxLocals);
      }
    };
  }

  private static Object[] entryLocals(String owner, int access, String descriptor) {
    List<Object> locals = new ArrayList<Object>();
    if ((access & Opcodes.ACC_STATIC) == 0) locals.add(owner);
    for (Type argument : Type.getArgumentTypes(descriptor)) {
      switch (argument.getSort()) {
        case Type.BOOLEAN: case Type.BYTE: case Type.CHAR: case Type.SHORT: case Type.INT:
          locals.add(Opcodes.INTEGER); break;
        case Type.FLOAT: locals.add(Opcodes.FLOAT); break;
        case Type.LONG: locals.add(Opcodes.LONG); break;
        case Type.DOUBLE: locals.add(Opcodes.DOUBLE); break;
        case Type.ARRAY: locals.add(argument.getDescriptor()); break;
        default: locals.add(argument.getInternalName());
      }
    }
    return locals.toArray();
  }

  private static MethodVisitor outbound(MethodVisitor method) {
    return new MethodVisitor(Opcodes.ASM9, method) {
      @Override public void visitInsn(int opcode) {
        if (opcode == Opcodes.ARETURN) {
          super.visitInsn(Opcodes.DUP);
          super.visitVarInsn(Opcodes.ALOAD, 0);
          super.visitInsn(Opcodes.SWAP);
          super.visitMethodInsn(Opcodes.INVOKESTATIC, HOOKS, "outbound",
              "(Ljava/lang/Object;Ljava/lang/Object;)V", false);
        }
        super.visitInsn(opcode);
      }
    };
  }

  private static MethodVisitor executor(MethodVisitor method) {
    return new MethodVisitor(Opcodes.ASM9, method) {
      @Override public void visitCode() {
        super.visitCode();
        super.visitVarInsn(Opcodes.ALOAD, 1);
        super.visitMethodInsn(Opcodes.INVOKESTATIC, HOOKS, "wrapTask",
            "(Ljava/lang/Runnable;)Ljava/lang/Runnable;", false);
        super.visitVarInsn(Opcodes.ASTORE, 1);
      }
    };
  }

  private static MethodVisitor shardResponseCompletion(MethodVisitor method) {
    return new MethodVisitor(Opcodes.ASM9, method) {
      @Override public void visitMethodInsn(int opcode, String owner, String name,
          String descriptor, boolean isInterface) {
        if ("org/apache/solr/handler/component/HttpShardHandler".equals(owner)
            && "request".equals(name)
            && "(Ljava/lang/String;Lorg/apache/solr/client/solrj/SolrRequest;)"
                .concat("Lorg/apache/solr/common/util/NamedList;").equals(descriptor)) {
          super.visitVarInsn(Opcodes.ALOAD, 0);
          super.visitMethodInsn(Opcodes.INVOKESTATIC, HOOKS, "beforeUnloadRequest",
              "(Ljava/lang/Object;)V", false);
        }
        super.visitMethodInsn(opcode, owner, name, descriptor, isInterface);
      }
      @Override public void visitInsn(int opcode) {
        if (opcode == Opcodes.ARETURN) {
          super.visitInsn(Opcodes.DUP);
          super.visitMethodInsn(Opcodes.INVOKESTATIC, HOOKS, "completedShardResponse",
              "(Ljava/lang/Object;)V", false);
        }
        super.visitInsn(opcode);
      }
    };
  }

  private static MethodVisitor shardResponseJoin(MethodVisitor method) {
    return new MethodVisitor(Opcodes.ASM9, method) {
      @Override public void visitMethodInsn(int opcode, String owner, String name,
          String descriptor, boolean isInterface) {
        super.visitMethodInsn(opcode, owner, name, descriptor, isInterface);
        if (opcode == Opcodes.INVOKEINTERFACE && "java/util/concurrent/Future".equals(owner)
            && "get".equals(name) && "()Ljava/lang/Object;".equals(descriptor)) {
          super.visitInsn(Opcodes.DUP);
          super.visitMethodInsn(Opcodes.INVOKESTATIC, HOOKS, "joinedShardResponse",
              "(Ljava/lang/Object;)V", false);
        }
      }
    };
  }

  private static MethodVisitor forceLeaderOperand(MethodVisitor method) {
    return new MethodVisitor(Opcodes.ASM9, method) {
      private boolean observed;
      @Override public void visitMethodInsn(int opcode, String owner, String name,
          String descriptor, boolean isInterface) {
        super.visitMethodInsn(opcode, owner, name, descriptor, isInterface);
        if (!observed && SLICE.equals(owner) && "getLeader".equals(name)
            && "()Lorg/apache/solr/common/cloud/Replica;".equals(descriptor)) {
          observed = true;
          super.visitInsn(Opcodes.DUP);
          super.visitVarInsn(Opcodes.ALOAD, 8); // selected Slice
          super.visitVarInsn(Opcodes.ALOAD, 7); // selected DocCollection
          super.visitVarInsn(Opcodes.ALOAD, 5); // resolved collection name
          super.visitVarInsn(Opcodes.ALOAD, 2); // serving ZkController
          super.visitMethodInsn(Opcodes.INVOKESTATIC, HOOKS, "forceLeaderOperand",
              "(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/String;Ljava/lang/Object;)V", false);
        }
      }
    };
  }

  private static MethodVisitor qualifiedStateRead(MethodVisitor method) {
    return new MethodVisitor(Opcodes.ASM9, method) {
      @Override public void visitMethodInsn(int opcode, String owner, String name,
          String descriptor, boolean isInterface) {
        if ("org/apache/solr/common/cloud/SolrZkClient".equals(owner)
            && "getData".equals(name)
            && "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Lorg/apache/zookeeper/data/Stat;Z)[B".equals(descriptor)) {
          // The existing call arguments remain on the operand stack.
          super.visitVarInsn(Opcodes.ALOAD, 1); // collection
          super.visitVarInsn(Opcodes.ALOAD, 4); // resolved collection path
          super.visitVarInsn(Opcodes.ALOAD, 2); // registered watcher
          super.visitMethodInsn(Opcodes.INVOKESTATIC, HOOKS, "beforeQualifiedStateRead",
              "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Object;)V", false);
        }
        super.visitMethodInsn(opcode, owner, name, descriptor, isInterface);
      }
    };
  }

  private static MethodVisitor qualifiedStateChildrenRead(MethodVisitor method) {
    return new MethodVisitor(Opcodes.ASM9, method) {
      @Override public void visitMethodInsn(int opcode, String owner, String name,
          String descriptor, boolean isInterface) {
        if ("org/apache/solr/common/cloud/SolrZkClient".equals(owner)
            && "getChildren".equals(name)
            && "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;"
                .concat("Lorg/apache/zookeeper/data/Stat;Z)Ljava/util/List;")
                .equals(descriptor)) {
          super.visitVarInsn(Opcodes.ALOAD, 0);
          super.visitMethodInsn(Opcodes.INVOKESTATIC, HOOKS, "beforeStateWatchChildren",
              "(Ljava/lang/Object;)V", false);
        }
        super.visitMethodInsn(opcode, owner, name, descriptor, isInterface);
      }
    };
  }
}
