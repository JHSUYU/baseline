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
  private static final String OVERSEER = "org/apache/solr/cloud/api/collections/OverseerCollectionMessageHandler";
  private static final String ALIASES = "org/apache/solr/common/cloud/ZkStateReader$AliasesManager";
  private static final String POOL = "org/apache/solr/common/util/ExecutorUtil$MDCAwareThreadPoolExecutor";

  @Override
  public byte[] transform(ClassLoader loader, String className, Class<?> classBeingRedefined,
      ProtectionDomain protectionDomain, byte[] classfileBuffer) {
    if (!ZK.equals(className) && !FILTER.equals(className) && !CLIENT_STATE.equals(className)
        && !CLIENT_ZK.equals(className)
        && !OVERSEER.equals(className) && !ALIASES.equals(className)
        && !HTTP1.equals(className) && !HTTP2.equals(className) && !POOL.equals(className)) return null;
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
          if (OVERSEER.equals(className) && "processMessage".equals(name))
            return scoped(method, "beginOverseer", "endOverseer", false,
                className, access, descriptor);
          if (ALIASES.equals(className) && ("setIfNewer".equals(name)
              || "process".equals(name) || "update".equals(name)
              || "applyModificationAndExportToZk".equals(name)))
            return scoped(method, "beginAliasesManager", "endAliasesManager", false,
                className, access, descriptor);
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
}
