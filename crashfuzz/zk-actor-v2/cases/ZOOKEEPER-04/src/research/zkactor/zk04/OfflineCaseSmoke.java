package research.zkactor.zk04;

import java.io.File;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.List;
import research.zkactor.Probe;

/** Same socket site across two peers: only follower2's registered client can match. */
public final class OfflineCaseSmoke {
  public static final class FakeTxnFactory {
    private final File dir;
    FakeTxnFactory(File dir) { this.dir = dir; }
    public File getSnapDir() { return dir; }
  }
  public static final class FakeServer {
    private final long sid;
    FakeServer(long sid) { this.sid = sid; }
    public long getServerId() { return sid; }
  }
  public static final class FakePeer {
    private final long sid;
    private final int port;
    private final FakeTxnFactory factory;
    private final FakeServer server;
    FakePeer(long sid, int port, File dir) {
      this.sid = sid; this.port = port; this.factory = new FakeTxnFactory(dir);
      this.server = new FakeServer(sid);
    }
    public long getMyId() { return sid; }
    public int getClientPort() { return port; }
    public FakeTxnFactory getTxnFactory() { return factory; }
    public FakeServer getActiveServer() { return server; }
  }
  public static final class FakePeerStruct {
    private final FakePeer peer;
    private final int clientPort;
    FakePeerStruct(FakePeer peer, int clientPort) {
      this.peer = peer; this.clientPort = clientPort;
    }
  }
  public static final class FakeUtil {
    private final int ALL = 3;
    private final FakePeerStruct[] peers = new FakePeerStruct[4];
    FakeUtil(String root) {
      for (int sid = 1; sid <= 3; sid++) {
        peers[sid] = new FakePeerStruct(new FakePeer(sid, 12000 + sid,
            new File(root, "s" + sid)), 12000 + sid);
      }
    }
    public FakePeerStruct getPeer(int sid) { return peers[sid]; }
    public List<FakePeer> getFollowerQuorumPeers() {
      return Arrays.asList(peers[1].peer, peers[2].peer);
    }
  }
  public static final class FakeZooKeeper {
    private final Object cnxn = new Object();
    public long getSessionId() { return 0x12345L; }
  }
  public static final class FakeConnection {
    private final FakeServer zkServer;
    private final int sourcePort;
    FakeConnection(FakeServer server, int sourcePort) {
      zkServer = server; this.sourcePort = sourcePort;
    }
    public InetSocketAddress getRemoteSocketAddress() {
      return new InetSocketAddress("127.0.0.1", sourcePort);
    }
  }
  public static final class FakeRequest {
    private final long session;
    FakeRequest(long session) { this.session = session; }
    public long getSessionId() { return session; }
    public long getLastZxidSeen() { return 10L; }
  }

  public static void main(String[] args) throws Exception {
    FakeUtil util = new FakeUtil(args[0]);
    FakeZooKeeper zk = new FakeZooKeeper();
    Bridge.registerTest(util, 1, 2, zk);
    Bridge.bindInitialSession(zk);
    String site = "org.apache.zookeeper.ClientCnxnSocketNIO#doIO:119:"
        + "java.nio.channels.SocketChannel#write(Ljava/nio/ByteBuffer;)I";
    Bridge.clientIoResolved(zk.cnxn, new Object(), 31001, 12001, site, "write");
    Bridge.clientIoResolved(new Object(), new Object(), 31002, 12002, site, "write");
    int applied = 0;
    try { Bridge.clientIoResolved(zk.cnxn, new Object(), 31003, 12002, site, "write"); }
    catch (IOException expected) { applied++; }
    Bridge.targetGuard(-1, util.peers[1].peer.server,
        new FakeConnection(util.peers[1].peer.server, 31001),
        new FakeRequest(0x12345L), 0x12345L);
    Bridge.targetGuard(-1, util.peers[2].peer.server,
        new FakeConnection(util.peers[2].peer.server, 31002),
        new FakeRequest(0x12345L), 0x12345L);
    Bridge.targetGuard(-1, util.peers[2].peer.server,
        new FakeConnection(util.peers[2].peer.server, 31003),
        new FakeRequest(0x12345L), 0x12345L);
    Probe.write(Paths.get(args[1]));
    List<String> rows = Files.readAllLines(Paths.get(args[1]));
    long matches = rows.stream().filter(row -> row.contains("\tFAULT_MATCHED\t")).count();
    long guards = rows.stream().filter(row -> row.contains("\tTARGET_GUARD\t")).count();
    long unbound = rows.stream().filter(row -> row.contains("\tUNBOUND_TARGET\t")).count();
    if (applied != 1 || matches != 1 || guards != 1 || unbound != 2) {
      throw new AssertionError("applied=" + applied + " matches=" + matches
          + " guards=" + guards + " unboundTarget=" + unbound);
    }
    System.out.println("zk04_applied=" + applied + " matches=" + matches
        + " selectedGuards=" + guards + " unboundTarget=" + unbound);
  }
}
