package research.zkactor;

import java.nio.file.Path;
import java.nio.file.Paths;

/** JVM -Xverify:all smoke: resolve rewritten originals from first classpath entry. */
public final class VerifyTransformed {
  private VerifyTransformed() {}

  public static void main(String[] args) throws Exception {
    if (args.length < 2) throw new IllegalArgumentException("directory and class names needed");
    Path directory = Paths.get(args[0]);
    for (int i = 1; i < args.length; i++) {
      String name = args[i].replace('/', '.');
      Class<?> checked = Class.forName(name, false, ClassLoader.getSystemClassLoader());
      Path origin = Paths.get(checked.getProtectionDomain().getCodeSource().getLocation().toURI());
      if (!origin.equals(directory)) {
        throw new AssertionError(name + " loaded from " + origin + " instead of " + directory);
      }
      checked.getDeclaredMethods();
      System.out.println("JVM_VERIFIED " + checked.getName());
    }
  }
}
