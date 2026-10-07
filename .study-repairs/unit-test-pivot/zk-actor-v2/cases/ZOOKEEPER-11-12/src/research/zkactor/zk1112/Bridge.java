package research.zkactor.zk1112;

import java.io.File;
import java.io.IOException;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.file.Path;
import research.zkactor.ActorRegistry;
import research.zkactor.Probe;

/** Joins real QuorumPeer/file receivers to the unchanged epoch-recovery JUnit. */
public final class Bridge {
  static final String CHECK11 = "ZOOKEEPER-11:QuorumPeer.loadDataBase:1169:currentEpoch.tmp.exists";
  static final String CHECK12 = "ZOOKEEPER-12:QuorumPeer.loadDataBase:1193:acceptedEpoch<currentEpoch";
  private static final ActorRegistry REGISTRY = new ActorRegistry();
  private static volatile long firstSid = -1;
  private static volatile Path firstSnapDir;
  private static final ThreadLocal<Boolean> LAST11 = new ThreadLocal<>();
  private static final ThreadLocal<Boolean> LAST12 = new ThreadLocal<>();

  private Bridge() {}

  private static Object call(Object receiver, String name) throws Exception {
    Method method = receiver.getClass().getMethod(name);
    return method.invoke(receiver);
  }

  private static Object field(Object receiver, String name) throws Exception {
    for (Class<?> type = receiver.getClass(); type != null; type = type.getSuperclass()) {
      try {
        Field f = type.getDeclaredField(name);
        f.setAccessible(true);
        return f.get(receiver);
      } catch (NoSuchFieldException ignored) { }
    }
    throw new NoSuchFieldException(receiver.getClass().getName() + "." + name);
  }

  private static long sid(Object peer) throws Exception {
    return ((Number) call(peer, "getMyId")).longValue();
  }

  private static File snap(Object peer) throws Exception {
    return (File) call(call(peer, "getTxnFactory"), "getSnapDir");
  }

  private static Path path(File file) {
    return file.toPath().toAbsolutePath().normalize();
  }

  private static void error(String stage, Throwable failure) {
    Probe.diagnostic("BINDING_ERROR", stage, failure.getClass().getName(),
        String.valueOf(failure.getMessage()));
  }

  public static void enterLoadDataBase(Object peer) {
    try {
      long id = sid(peer);
      File dir = snap(peer);
      REGISTRY.registerPeer(peer, id, dir, 0);
      Probe.diagnostic("PEER_BIND", Long.toString(id), dir.getAbsolutePath(),
          Integer.toString(System.identityHashCode(peer)));
    } catch (Throwable failure) { error("enterLoadDataBase", failure); }
  }

  /** Called just after the original test stores servers.mt[0] in local firstServer. */
  public static void selectFirstServer(Object mainThread) {
    try {
      Object peer = call(mainThread, "getQuorumPeer");
      long id = sid(peer);
      File dir = snap(peer);
      REGISTRY.registerPeer(peer, id, dir, 0);
      if (firstSid >= 0 && (firstSid != id || !path(dir).equals(firstSnapDir))) {
        throw new IllegalStateException("firstServer changed SID or snapshot directory");
      }
      firstSid = id;
      firstSnapDir = path(dir);
      Probe.diagnostic("FIRST_SERVER_BIND", Long.toString(id), dir.getAbsolutePath(),
          Integer.toString(System.identityHashCode(peer)));
    } catch (Throwable failure) { error("selectFirstServer", failure); }
  }

  private static ActorRegistry.TargetIdentity selected(Object peer) {
    try {
      if (firstSid < 0 || sid(peer) != firstSid || firstSnapDir == null ||
          !path(snap(peer)).equals(firstSnapDir)) return null;
      ActorRegistry.TargetIdentity target = REGISTRY.target(peer, "firstServer", 0);
      return target.bound() && Long.toString(firstSid).equals(target.peer) ? target : null;
    } catch (Throwable failure) { error("selected", failure); return null; }
  }

  private static boolean selectedFile(File file) {
    return firstSid >= 0 && firstSnapDir != null && file != null &&
        firstSnapDir.equals(path(file).getParent());
  }

  private static ActorRegistry.IoIdentity peerFile(Object peer, File file, String operation) {
    try {
      ActorRegistry.IoIdentity identity = REGISTRY.epochFileIo(peer, file, operation);
      Probe.diagnostic("FILE_RAW", operation, Long.toString(sid(peer)),
          file.getAbsolutePath(), identity.bound() ? identity.actor : identity.unboundReason);
      return identity;
    } catch (Throwable failure) { error("peerFile", failure); return null; }
  }

  public static void peerFileIo(Object peer, File file, String site, String operation)
      throws IOException {
    Probe.io(site, peerFile(peer, file, operation));
  }

  public static void testFileIo(File file, String site) throws IOException {
    ActorRegistry.IoIdentity identity = REGISTRY.epochFileIo(file, "test_write");
    if (!selectedFile(file) || !identity.bound() ||
        !Long.toString(firstSid).equals(identity.localPeer)) identity = null;
    Probe.diagnostic("TEST_FILE_RAW", file == null ? "" : file.getAbsolutePath(),
        Long.toString(firstSid), identity == null ? "unbound" : identity.actor);
    Probe.io(site, identity);
  }

  /** Uses AtomicFileOutputStream's actual origFile/tmpFile fields, never a guessed path. */
  public static void atomicFileIo(Object stream, String site, String operation)
      throws IOException {
    ActorRegistry.IoIdentity identity = null;
    try {
      File original = (File) field(stream, "origFile");
      File temporary = (File) field(stream, "tmpFile");
      boolean pair = path(temporary).equals(path(new File(original.getParentFile(),
          original.getName() + ".tmp")));
      if (pair) identity = REGISTRY.epochFileIo(original, operation);
      Probe.diagnostic("ATOMIC_FILE_RAW", operation, original.getAbsolutePath(),
          temporary.getAbsolutePath(), identity == null ? "unbound" :
              identity.bound() ? identity.actor : identity.unboundReason);
    } catch (Throwable failure) { error("atomicFileIo", failure); }
    Probe.io(site, identity);
  }

  public static void guard11(boolean tmpExists, Object peer, File tmp,
      long zxidEpoch, long currentEpoch) {
    ActorRegistry.TargetIdentity target = selected(peer);
    ActorRegistry.IoIdentity file = peerFile(peer, tmp, "exists");
    if (!selectedFile(tmp) || file == null || !file.bound() || target == null) {
      LAST11.remove();
      Probe.targetGuard(CHECK11, null, "unbound-file-or-peer");
      return;
    }
    LAST11.set(tmpExists);
    Probe.targetGuard(CHECK11, target, "tmpExists=" + tmpExists
        + ";zxidEpoch=" + zxidEpoch + ";currentEpoch=" + currentEpoch);
  }

  public static void throw11(Throwable failure, Object peer) {
    ActorRegistry.TargetIdentity target = selected(peer);
    Boolean exists = LAST11.get();
    LAST11.remove();
    if (target == null || !Boolean.FALSE.equals(exists) ||
        !(failure instanceof IOException) || failure.getMessage() == null ||
        !failure.getMessage().startsWith("The current epoch, ") ||
        !failure.getMessage().contains("is older than the last zxid")) return;
    Probe.targetThrow(CHECK11, target, failure.getClass().getName());
  }

  public static void guard12(Object peer, long accepted, long current) {
    ActorRegistry.TargetIdentity target = selected(peer);
    if (target == null) {
      LAST12.remove();
      Probe.targetGuard(CHECK12, null, "unbound-peer");
      return;
    }
    LAST12.set(accepted < current);
    Probe.targetGuard(CHECK12, target, "accepted=" + accepted + ";current=" + current
        + ";less=" + (accepted < current));
  }

  public static void throw12(Throwable failure, Object peer) {
    ActorRegistry.TargetIdentity target = selected(peer);
    Boolean less = LAST12.get();
    LAST12.remove();
    if (target == null || !Boolean.TRUE.equals(less) ||
        !(failure instanceof IOException) || failure.getMessage() == null ||
        !failure.getMessage().startsWith("The accepted epoch, ") ||
        !failure.getMessage().contains("is less than the current epoch")) return;
    Probe.targetThrow(CHECK12, target, failure.getClass().getName());
  }
}
