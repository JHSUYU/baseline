package edu.uva.liftlab.mallory.solr31;

import java.lang.instrument.ClassFileTransformer;
import java.security.ProtectionDomain;
import java.security.MessageDigest;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Future-only add-on. Install after the ordinary SolrTransformer. */
public final class RetryAttemptTransformer implements ClassFileTransformer {
  private static final String CLIENT = "org/apache/solr/common/cloud/SolrZkClient";
  private static final String KEEPER = "org/apache/solr/common/cloud/SolrZooKeeper";
  private static final String GET_DATA =
      "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Lorg/apache/zookeeper/data/Stat;)[B";
  private static final String HOOK = "edu/uva/liftlab/mallory/solr31/RetryAttemptHook";
  private static final String ORIGINAL_SHA256 =
      "51b3131fed142509b80da408d0d3f8d036045237b51a48c2a4dd9cf574a72dc0";

  @Override
  public byte[] transform(ClassLoader loader, String name, Class<?> redefined,
      ProtectionDomain domain, byte[] bytes) {
    if (!CLIENT.equals(name)) return null;
    String originalHash = sha256(bytes);
    if (!ORIGINAL_SHA256.equals(originalHash)) {
      System.err.println("MALLORY_SOLR31_RETRY_WEAVE status=invalid original_sha256="
          + originalHash);
      return null;
    }
    final int[] matches = {0};
    ClassReader reader = new ClassReader(bytes);
    ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_MAXS);
    reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
      @Override public MethodVisitor visitMethod(int access, String methodName,
          String descriptor, String signature, String[] exceptions) {
        MethodVisitor downstream = super.visitMethod(access, methodName, descriptor,
            signature, exceptions);
        if (!methodName.startsWith("lambda$getData$") || !GET_DATA.equals(descriptor)
            || (access & Opcodes.ACC_STATIC) != 0) return downstream;
        return new MethodVisitor(Opcodes.ASM9, downstream) {
          @Override public void visitMethodInsn(int opcode, String owner, String callName,
              String callDescriptor, boolean isInterface) {
            if (opcode == Opcodes.INVOKEVIRTUAL && KEEPER.equals(owner)
                && "getData".equals(callName) && GET_DATA.equals(callDescriptor)) {
              matches[0]++;
              // Preserve the original keeper/path/wrapped-watcher/stat operand stack.
              super.visitVarInsn(Opcodes.ALOAD, 0); // SolrZkClient
              super.visitVarInsn(Opcodes.ALOAD, 1); // path
              super.visitVarInsn(Opcodes.ALOAD, 2); // original StateWatcher
              super.visitVarInsn(Opcodes.ALOAD, 3); // same Stat for all retries
              super.visitMethodInsn(Opcodes.INVOKESTATIC, HOOK, "beforeAttempt",
                  "(Ljava/lang/Object;Ljava/lang/String;Ljava/lang/Object;Ljava/lang/Object;)V",
                  false);
              super.visitMethodInsn(opcode, owner, callName, callDescriptor, isInterface);
              // A successful low-level return leaves byte[] on the stack.
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ALOAD, 1);
              super.visitVarInsn(Opcodes.ALOAD, 2);
              super.visitVarInsn(Opcodes.ALOAD, 3);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, HOOK, "afterSuccess",
                  "(Ljava/lang/Object;Ljava/lang/String;Ljava/lang/Object;Ljava/lang/Object;)V",
                  false);
            } else {
              super.visitMethodInsn(opcode, owner, callName, callDescriptor, isInterface);
            }
          }
        };
      }
    }, 0);
    // Transformer exceptions can be ignored by the JVM. The runner must also require this
    // marker plus an exact low-level DOOR_OBSERVED catalog/trace before admitting faults.
    if (matches[0] != 1) {
      System.err.println("MALLORY_SOLR31_RETRY_WEAVE status=invalid matches=" + matches[0]);
      return null;
    }
    System.err.println("MALLORY_SOLR31_RETRY_WEAVE status=ok matches=1 original_sha256="
        + originalHash + " loader=" + (loader == null ? "bootstrap"
        : loader.getClass().getName() + "@"
        + Integer.toHexString(System.identityHashCode(loader))));
    return writer.toByteArray();
  }

  private static String sha256(byte[] bytes) {
    try {
      byte[] digest = MessageDigest.getInstance("SHA-256").digest(bytes);
      StringBuilder result = new StringBuilder(digest.length * 2);
      for (byte value : digest) result.append(String.format("%02x", value & 0xff));
      return result.toString();
    } catch (Exception failure) {
      throw new IllegalStateException("SHA-256 unavailable", failure);
    }
  }
}
