package research.zkactor.zk01;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.List;
import research.zkactor.Probe;

/** Two clients at the same static callsite: only the selected actor can match. */
public final class OfflineCaseSmoke {
  public static final class FakeTxnFactory {
    private final File snapDir;
    FakeTxnFactory(File snapDir) { this.snapDir = snapDir; }
    public File getSnapDir() { return snapDir; }
  }

  public static final class FakePeer {
    private final long sid;
    private final FakeTxnFactory txnFactory;
    FakePeer(long sid, File snapDir) {
      this.sid = sid;
      this.txnFactory = new FakeTxnFactory(snapDir);
    }
    public long getMyId() { return sid; }
    public FakeTxnFactory getTxnFactory() { return txnFactory; }
  }

  public static final class FakeMain {
    private final FakePeer quorumPeer;
    FakeMain(FakePeer quorumPeer) { this.quorumPeer = quorumPeer; }
  }

  public static final class FakeTest {
    private final FakeMain[] qpMain;
    private final int[] clientPorts;
    FakeTest(FakeMain[] qpMain, int[] clientPorts) {
      this.qpMain = qpMain;
      this.clientPorts = clientPorts;
    }
  }

  public static final class FakeZooKeeper {
    private final Object cnxn;
    FakeZooKeeper(Object cnxn) { this.cnxn = cnxn; }
  }

  public static void main(String[] args) throws Exception {
    Object creator = new Object();
    Object verifier = new Object();
    Object creatorChannel = new Object();
    Object otherCreatorChannel = new Object();
    Object verifierChannel = new Object();
    FakeMain[] peers = {
        new FakeMain(new FakePeer(0, new File(args[0], "peer0"))),
        new FakeMain(new FakePeer(1, new File(args[0], "peer1"))),
        new FakeMain(new FakePeer(2, new File(args[0], "peer2")))};
    Bridge.enterTest(new FakeTest(peers, new int[] {12000, 12001, 12002}), 1);
    Bridge.registerZooKeeper(new FakeZooKeeper(creator), "creatorCloser", 1);
    Bridge.registerZooKeeper(new FakeZooKeeper(verifier), "verifier", 1);
    String site = "ClientCnxnSocketNIO#doIO:119:SocketChannel.write";
    Bridge.clientIoResolved(verifier, verifierChannel, 12001, site, "write");
    Bridge.clientIoResolved(creator, otherCreatorChannel, 12002, site, "write");
    Bridge.clientIoResolved(new Object(), new Object(), 12001, site, "write");
    int applied = 0;
    try { Bridge.clientIoResolved(creator, creatorChannel, 12001, site, "write"); }
    catch (IOException expected) { applied++; }
    Bridge.clientIoResolved(creator, creatorChannel, 12001, site, "write");
    Probe.write(Paths.get(args[1]));
    List<String> lines = Files.readAllLines(Paths.get(args[1]));
    long matched = lines.stream().filter(line -> line.contains("\tFAULT_MATCHED\t")).count();
    long unbound = lines.stream().filter(line -> line.contains("\tUNBOUND_IO\t")).count();
    if (applied != 1 || matched != 1 || unbound != 1) {
      throw new AssertionError("applied=" + applied + " matched=" + matched
          + " unbound=" + unbound);
    }
    System.out.println("zk01_adapter_applied=" + applied + " matched=" + matched
        + " unbound=" + unbound);
  }
}
