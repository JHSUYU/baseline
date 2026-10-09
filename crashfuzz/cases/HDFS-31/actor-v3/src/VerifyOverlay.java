/** Offline linkage and bytecode verification only; never starts a MiniDFSCluster. */
public final class VerifyOverlay {
  public static void main(String[] args) throws Exception {
    for (String name : args) {
      Class<?> type = Class.forName(name, false, VerifyOverlay.class.getClassLoader());
      System.out.println(type.getName());
    }
  }
}
