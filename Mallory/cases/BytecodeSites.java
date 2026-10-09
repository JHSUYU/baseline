import edu.uva.liftlab.mallory.shaded.asm.ClassReader;
import edu.uva.liftlab.mallory.shaded.asm.Opcodes;
import edu.uva.liftlab.mallory.shaded.asm.tree.AbstractInsnNode;
import edu.uva.liftlab.mallory.shaded.asm.tree.ClassNode;
import edu.uva.liftlab.mallory.shaded.asm.tree.JumpInsnNode;
import edu.uva.liftlab.mallory.shaded.asm.tree.LineNumberNode;
import edu.uva.liftlab.mallory.shaded.asm.tree.LookupSwitchInsnNode;
import edu.uva.liftlab.mallory.shaded.asm.tree.MethodInsnNode;
import edu.uva.liftlab.mallory.shaded.asm.tree.MethodNode;
import edu.uva.liftlab.mallory.shaded.asm.tree.TableSwitchInsnNode;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/** Dump the instruction ordering used by MalloryTransformer from actual class bytes. */
public final class BytecodeSites {
  public static void main(String[] args) throws Exception {
    if (args.length != 3) throw new IllegalArgumentException("JAR_OR_CLASSES CLASS METHOD");
    Path source = Paths.get(args[0]);
    ZipFile jar = Files.isDirectory(source) ? null : new ZipFile(args[0]);
    try {
      String classPath = args[1].replace('.', '/') + ".class";
      InputStream stream;
      if (jar != null) {
        ZipEntry entry = jar.getEntry(classPath);
        if (entry == null) throw new IllegalArgumentException("class absent: " + classPath);
        stream = jar.getInputStream(entry);
      } else {
        stream = Files.newInputStream(source.resolve(classPath));
      }
      ClassNode clazz = new ClassNode();
      try { new ClassReader(stream).accept(clazz, ClassReader.EXPAND_FRAMES); }
      finally { stream.close(); }
      for (MethodNode method : clazz.methods) {
        if (!method.name.equals(args[2])) continue;
        System.out.println("M\t" + method.name + "\t" + method.desc);
        int line = -1;
        int branch = 0;
        int invocation = 0;
        int sequence = 0;
        for (AbstractInsnNode instruction : method.instructions.toArray()) {
          sequence++;
          if (instruction instanceof LineNumberNode) {
            line = ((LineNumberNode) instruction).line;
            continue;
          }
          int opcode = instruction.getOpcode();
          if ((instruction instanceof JumpInsnNode &&
               ((opcode >= Opcodes.IFEQ && opcode <= Opcodes.IF_ACMPNE)
                || opcode == Opcodes.IFNULL || opcode == Opcodes.IFNONNULL))
              || instruction instanceof TableSwitchInsnNode
              || instruction instanceof LookupSwitchInsnNode) {
            System.out.println("B\t" + sequence + "\t" + line + "\t" + (++branch)
                               + "\t" + opcode);
          } else if (opcode == Opcodes.ATHROW) {
            System.out.println("T\t" + sequence + "\t" + line);
          } else if (instruction instanceof MethodInsnNode) {
            MethodInsnNode call = (MethodInsnNode) instruction;
            System.out.println("C\t" + sequence + "\t" + line + "\t" + (++invocation) + "\t"
                               + call.owner + "#" + call.name + call.desc);
          }
        }
      }
    } finally { if (jar != null) jar.close(); }
  }
}
