package research.solr18;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Arrays;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Offline exact-site ASM overlay for the original Solr 8.11.4 classes. */
public final class PatchSolr18 {
  private static final String MANAGER = "org/apache/solr/common/cloud/ZkStateReader$AliasesManager";
  private static final String ALIASES = "Lorg/apache/solr/common/cloud/Aliases;";
  private static final String PROBE = "research/solr18/Solr18Probe";

  public static void main(String[] args) throws Exception {
    if (args.length != 3) throw new IllegalArgumentException("input class, name, classes directory required");
    byte[] original = Files.readAllBytes(Paths.get(args[0]));
    final String className = args[1];
    final int[] counts = new int[7];
    ClassReader reader = new ClassReader(original);
    ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_MAXS);
    reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
      @Override public MethodVisitor visitMethod(int access, String name, String descriptor,
          String signature, String[] exceptions) {
        MethodVisitor mv = super.visitMethod(access, name, descriptor, signature, exceptions);
        if (mv == null) return null;
        final boolean target = className.equals(MANAGER) && name.equals("setIfNewer")
            && descriptor.equals("(" + ALIASES + ")Z");
        final boolean apply = className.equals(MANAGER) && name.equals("applyModificationAndExportToZk")
            && descriptor.equals("(Ljava/util/function/UnaryOperator;)V");
        final boolean zkClient = className.equals("org/apache/solr/common/cloud/SolrZkClient");
        final boolean getData = zkClient && name.equals("getData")
            && descriptor.equals("(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Lorg/apache/zookeeper/data/Stat;Z)[B");
        final boolean setData = zkClient && name.equals("setData")
            && descriptor.equals("(Ljava/lang/String;[BIZ)Lorg/apache/zookeeper/data/Stat;");
        final boolean exists = zkClient && name.equals("exists")
            && descriptor.equals("(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Z)Lorg/apache/zookeeper/data/Stat;");
        return new MethodVisitor(Opcodes.ASM9, mv) {
          private int line = -1;
          @Override public void visitCode() {
            super.visitCode();
            if (apply) {
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "applyModification",
                  "(Ljava/lang/Object;)V", false);
              counts[3]++;
            }
            if (getData || setData || exists) {
              super.visitLdcInsn(getData ? "getData" : setData ? "setData" : "exists");
              super.visitVarInsn(Opcodes.ALOAD, 1);
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "aliasIo",
                  "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Object;)V", false);
              counts[getData ? 4 : setData ? 5 : 6]++;
            }
          }
          private void loadTargetContext() {
            super.visitVarInsn(Opcodes.ALOAD, 0);
            super.visitVarInsn(Opcodes.ALOAD, 0);
            super.visitFieldInsn(Opcodes.GETFIELD, MANAGER, "aliases", ALIASES);
            super.visitVarInsn(Opcodes.ALOAD, 1);
            super.visitVarInsn(Opcodes.ILOAD, 3);
          }
          @Override public void visitLineNumber(int number, Label start) {
            line = number;
            super.visitLineNumber(number, start);
            if (target && number == 2347) {
              loadTargetContext();
              super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "guard",
                  "(Ljava/lang/Object;" + ALIASES + ALIASES + "I)V", false);
              counts[0]++;
            }
          }
          @Override public void visitMethodInsn(int opcode, String owner, String called,
              String desc, boolean isInterface) {
            super.visitMethodInsn(opcode, owner, called, desc, isInterface);
            if (target && line == 2347 && owner.equals("java/util/Arrays")
                && called.equals("equals") && desc.equals("([B[B)Z")) {
              super.visitInsn(Opcodes.DUP);
              loadTargetContext();
              super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "equalResult",
                  "(ZLjava/lang/Object;" + ALIASES + ALIASES + "I)V", false);
              counts[1]++;
            }
          }
          @Override public void visitInsn(int opcode) {
            if (target && line == 2347 && opcode == Opcodes.ATHROW) {
              super.visitInsn(Opcodes.DUP);
              loadTargetContext();
              super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "targetThrow",
                  "(Ljava/lang/Throwable;Ljava/lang/Object;" + ALIASES + ALIASES + "I)V", false);
              counts[2]++;
            }
            super.visitInsn(opcode);
          }
        };
      }
    }, 0);
    if (className.equals(MANAGER) && !Arrays.equals(counts, new int[]{1,1,1,1,0,0,0}))
      throw new IllegalStateException("AliasesManager patch counts " + Arrays.toString(counts));
    if (className.equals("org/apache/solr/common/cloud/SolrZkClient")
        && !Arrays.equals(counts, new int[]{0,0,0,0,1,1,1}))
      throw new IllegalStateException("SolrZkClient patch counts " + Arrays.toString(counts));
    Path output = Paths.get(args[2], className + ".class");
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println(className + " patch counts " + Arrays.toString(counts));
  }
}
