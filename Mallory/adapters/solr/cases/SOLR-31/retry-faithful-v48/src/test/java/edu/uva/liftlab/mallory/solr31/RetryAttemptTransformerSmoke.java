package edu.uva.liftlab.mallory.solr31;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Offline check against the pinned Solr distribution class, without starting a cluster. */
public final class RetryAttemptTransformerSmoke {
  private static final String CLASS = "org/apache/solr/common/cloud/SolrZkClient.class";
  private static final String HOOK = "edu/uva/liftlab/mallory/solr31/RetryAttemptHook";

  public static void main(String[] args) throws Exception {
    if (args.length != 1) throw new IllegalArgumentException("expected pinned SolrJ jar");
    byte[] original;
    try (ZipFile jar = new ZipFile(args[0])) {
      ZipEntry entry = jar.getEntry(CLASS);
      if (entry == null) throw new AssertionError("SolrZkClient missing");
      try (InputStream input = jar.getInputStream(entry);
          ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
        byte[] buffer = new byte[8192];
        int length;
        while ((length = input.read(buffer)) != -1) bytes.write(buffer, 0, length);
        original = bytes.toByteArray();
      }
    }
    RetryAttemptTransformer transformer = new RetryAttemptTransformer();
    byte[] woven = transformer.transform(null, CLASS.substring(0, CLASS.length() - 6),
        null, null, original);
    if (woven == null) throw new AssertionError("pinned class did not weave");
    final int[] before = {0};
    final int[] after = {0};
    new ClassReader(woven).accept(new ClassVisitor(Opcodes.ASM9) {
      @Override public MethodVisitor visitMethod(int access, String name, String descriptor,
          String signature, String[] exceptions) {
        if (!name.startsWith("lambda$getData$") || !descriptor.endsWith(")[B")) return null;
        return new MethodVisitor(Opcodes.ASM9) {
          @Override public void visitMethodInsn(int opcode, String owner, String method,
              String desc, boolean isInterface) {
            if (opcode == Opcodes.INVOKESTATIC && HOOK.equals(owner)) {
              if ("beforeAttempt".equals(method)) before[0]++;
              if ("afterSuccess".equals(method)) after[0]++;
            }
          }
        };
      }
    }, 0);
    if (before[0] != 1 || after[0] != 1) {
      throw new AssertionError("expected one low-level before/success pair: "
          + before[0] + "/" + after[0]);
    }
    byte[] wrong = original.clone();
    wrong[wrong.length - 1] ^= 1;
    if (transformer.transform(null, CLASS.substring(0, CLASS.length() - 6),
        null, null, wrong) != null) throw new AssertionError("modified class accepted");
    System.out.println("SOLR31_RETRY_WEAVE_SMOKE ok before=1 after=1");
  }
}
