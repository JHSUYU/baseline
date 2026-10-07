package research.zkactor.zk1112;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.List;
import research.zkactor.Probe;

/** Two peers and two epoch files at one callsite: only the exact peer/file matches. */
public final class OfflineCaseSmoke {
  public static final class Txn {
    private final File snapDir;
    public Txn(File file) { snapDir = file; }
    public File getSnapDir() { return snapDir; }
  }
  public static final class Peer {
    private final long myid;
    private final Txn txn;
    public Peer(long sid, File dir) { myid = sid; txn = new Txn(dir); }
    public long getMyId() { return myid; }
    public Txn getTxnFactory() { return txn; }
  }
  public static final class MainThread {
    private final Peer peer;
    public MainThread(Peer value) { peer = value; }
    public Peer getQuorumPeer() { return peer; }
  }
  public static void main(String[] args) throws Exception {
    File p0 = new File(args[0], "peer0");
    File p1 = new File(args[0], "peer1");
    Peer peer0 = new Peer(0, p0);
    Peer peer1 = new Peer(1, p1);
    Bridge.enterLoadDataBase(peer0);
    Bridge.enterLoadDataBase(peer1);
    Bridge.selectFirstServer(new MainThread(peer0));
    String site = "QuorumPeer#readLongFromFile:2186:FileReader";
    Bridge.peerFileIo(peer1, new File(p1, "currentEpoch"), site, "read");
    Bridge.peerFileIo(peer0, new File(p1, "currentEpoch"), site, "read");
    Bridge.peerFileIo(peer0, new File(p0, "acceptedEpoch"), site, "read");
    Bridge.peerFileIo(peer0, new File(p0, "currentEpoch.tmp"), site, "read");
    int applied = 0;
    try { Bridge.peerFileIo(peer0, new File(p0, "currentEpoch"), site, "read"); }
    catch (IOException expected) { applied++; }
    Bridge.guard11(false, peer1, new File(p1, "currentEpoch.tmp"), 2, 1);
    Bridge.guard11(false, peer0, new File(p0, "currentEpoch.tmp"), 2, 1);
    Bridge.guard12(peer1, 1, 2);
    Bridge.guard12(peer0, 2, 2);
    Probe.write(Paths.get(args[1]));
    List<String> events = Files.readAllLines(Paths.get(args[1]));
    long faults = events.stream().filter(x -> x.contains("\tFAULT_APPLIED\t")).count();
    long unbound = events.stream().filter(x -> x.contains("\tUNBOUND_IO\t")).count();
    long selected11 = events.stream().filter(x -> x.contains("\tTARGET_GUARD\t" + Bridge.CHECK11
        + "\tpeer:0\tfirstServer\t0\t")).count();
    long selected12 = events.stream().filter(x -> x.contains("\tTARGET_GUARD\t" + Bridge.CHECK12
        + "\tpeer:0\tfirstServer\t0\t")).count();
    if (applied != 1 || faults != 1 || unbound < 1 || selected11 != 1 || selected12 != 1)
      throw new AssertionError("wrong-peer/file smoke failed: " + applied + "/" + faults
          + " unbound=" + unbound + " targets=" + selected11 + "/" + selected12);
    System.out.println("ZK1112_WRONG_PEER_FILE_OK applied=" + applied
        + " unbound=" + unbound + " target11=" + selected11 + " target12=" + selected12);
  }
}
