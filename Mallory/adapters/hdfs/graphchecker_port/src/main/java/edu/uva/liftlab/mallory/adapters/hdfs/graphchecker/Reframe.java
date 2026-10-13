package edu.uva.liftlab.mallory.adapters.hdfs.graphchecker;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;

/** Recompute stack maps for an isolated patched class. */
public final class Reframe {
  private Reframe() { }

  public static void main(String[] args) throws Exception {
    if (args.length != 1) throw new IllegalArgumentException("expected one class path");
    Path path = Paths.get(args[0]);
    ClassReader reader = new ClassReader(Files.readAllBytes(path));
    ClassWriter writer = new ClassWriter(reader,
        ClassWriter.COMPUTE_FRAMES | ClassWriter.COMPUTE_MAXS) {
      @Override protected String getCommonSuperClass(String left, String right) {
        try {
          return super.getCommonSuperClass(left, right);
        } catch (RuntimeException | LinkageError missingFromIsolatedLoader) {
          return "java/lang/Object";
        }
      }
    };
    reader.accept(writer, ClassReader.SKIP_FRAMES);
    Files.write(path, writer.toByteArray());
  }
}
