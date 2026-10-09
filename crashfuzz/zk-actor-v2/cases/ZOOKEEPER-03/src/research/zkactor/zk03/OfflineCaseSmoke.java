package research.zkactor.zk03;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.List;
import research.zkactor.Probe;

/** Same static socket site, same raw session, distinct handle and peer actors. */
public final class OfflineCaseSmoke {
  public static final class FakeTxnFactory {
    private final File dir;
    FakeTxnFactory(File dir) { this.dir = dir; }
    public File getSnapDir() { return dir; }
  }

  public static final class FakePeer {
    private final long sid;
    private final FakeTxnFactory factory;
    private final Object leader;
    FakePeer(long sid, File dir) {
      this.sid = sid;
      this.factory = new FakeTxnFactory(dir);
      this.leader = sid == 5 ? new Object() : null;
    }
    public long getMyId() { return sid; }
    public FakeTxnFactory getTxnFactory() { return factory; }
  }

  public static final class FakeQB {
    private final String hostPort = "127.0.0.1:12001,127.0.0.1:12002,127.0.0.1:12003,"
        + "127.0.0.1:12004,127.0.0.1:12005";
    private final int portClient1 = 12001, portClient2 = 12002, portClient3 = 12003,
        portClient4 = 12004, portClient5 = 12005;
    private final FakePeer s1, s2, s3, s4, s5;
    FakeQB(String root) {
      s1 = new FakePeer(1, new File(root, "s1"));
      s2 = new FakePeer(2, new File(root, "s2"));
      s3 = new FakePeer(3, new File(root, "s3"));
      s4 = new FakePeer(4, new File(root, "s4"));
      s5 = new FakePeer(5, new File(root, "s5"));
    }
  }

  public static final class FakeTest {
    private final FakeQB qb;
    FakeTest(String root) { qb = new FakeQB(root); }
  }

  public static final class FakeHandle {
    private final Object cnxn = new Object();
    private final long session;
    FakeHandle(long session) { this.session = session; }
    public long getSessionId() { return session; }
  }

  public static final class FakeServer {
    private final long sid;
    FakeServer(long sid) { this.sid = sid; }
    public long getServerId() { return sid; }
  }

  public static final class FakeTracker {
    private final FakeServer expirer;
    FakeTracker(long sid) { expirer = new FakeServer(sid); }
  }

  public static final class FakeSession {
    private final boolean closing;
    FakeSession(boolean closing) { this.closing = closing; }
    public boolean isClosing() { return closing; }
  }

  public static void main(String[] args) throws Exception {
    Bridge.enterTest(new FakeTest(args[0]));
    FakeHandle initial = new FakeHandle(0x12345L);
    FakeHandle moved = new FakeHandle(0x12345L);
    Bridge.registerInitial(initial);
    Bridge.registerMoved(moved, 0, initial);
    String site = "ClientCnxnSocketNIO#doIO:119:SocketChannel.write";
    Bridge.clientIoResolved(initial.cnxn, new Object(), 12001, site, "write");
    Bridge.clientIoResolved(moved.cnxn, new Object(), 12003, site, "write");
    Bridge.clientIoResolved(new Object(), new Object(), 12002, site, "write");
    Object channel = new Object();
    int applied = 0;
    try { Bridge.clientIoResolved(moved.cnxn, channel, 12002, site, "write"); }
    catch (IOException expected) { applied++; }
    Bridge.clientIoResolved(moved.cnxn, channel, 12002, site, "write");
    Object localOwner = Class.forName("org.apache.zookeeper.server.ServerCnxn")
        .getDeclaredField("me").get(null);
    FakeTracker leader = new FakeTracker(5);
    Bridge.targetGuard(leader, 0x12345L, localOwner, new FakeSession(false));
    Bridge.targetGuard(leader, 0x12345L, localOwner, null);
    Bridge.targetGuard(new FakeTracker(4), 0x12345L, localOwner, new FakeSession(false));
    Bridge.targetGuard(leader, 0x777L, localOwner, new FakeSession(false));
    Bridge.targetGuard(leader, 0x12345L, new Object(), new FakeSession(false));
    Throwable expired = (Throwable) Class.forName(
        "org.apache.zookeeper.KeeperException$SessionExpiredException")
        .getDeclaredConstructor().newInstance();
    Bridge.targetThrow(expired, leader, 0x12345L, localOwner, null);
    Probe.write(Paths.get(args[1]));
    List<String> rows = Files.readAllLines(Paths.get(args[1]));
    long matched = rows.stream().filter(row -> row.contains("\tFAULT_MATCHED\t")).count();
    long unbound = rows.stream().filter(row -> row.contains("\tUNBOUND_IO\t")).count();
    long wrongDestination = rows.stream()
        .filter(row -> row.contains("\tDESTINATION_MISMATCH\t")).count();
    long guards = rows.stream().filter(row -> row.contains("\tTARGET_GUARD\t")).count();
    long throwsSelected = rows.stream().filter(row -> row.contains("\tTARGET_THROW\t")).count();
    long unboundTargets = rows.stream().filter(row -> row.contains("\tUNBOUND_TARGET\t")).count();
    if (applied != 1 || matched != 1 || unbound != 2 || wrongDestination != 1
        || guards != 2 || throwsSelected != 1 || unboundTargets != 3) {
      throw new AssertionError("applied=" + applied + " matched=" + matched
          + " unbound=" + unbound + " wrongDestination=" + wrongDestination
          + " guards=" + guards + " throws=" + throwsSelected
          + " unboundTargets=" + unboundTargets);
    }
    System.out.println("zk03_applied=" + applied + " matched=" + matched
        + " unbound=" + unbound + " wrongDestination=" + wrongDestination
        + " guards=" + guards + " throws=" + throwsSelected
        + " unboundTargets=" + unboundTargets);
  }
}
