package research.zkactor.zk02;

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
    Probe.write(Paths.get(args[1]));
    List<String> rows = Files.readAllLines(Paths.get(args[1]));
    long matched = rows.stream().filter(row -> row.contains("\tFAULT_MATCHED\t")).count();
    long unbound = rows.stream().filter(row -> row.contains("\tUNBOUND_IO\t")).count();
    long wrongDestination = rows.stream()
        .filter(row -> row.contains("\tDESTINATION_MISMATCH\t")).count();
    if (applied != 1 || matched != 1 || unbound != 2 || wrongDestination != 1) {
      throw new AssertionError("applied=" + applied + " matched=" + matched
          + " unbound=" + unbound + " wrongDestination=" + wrongDestination);
    }
    System.out.println("zk02_applied=" + applied + " matched=" + matched
        + " unbound=" + unbound + " wrongDestination=" + wrongDestination);
  }
}
