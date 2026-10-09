package research.zkactor;

import java.io.File;
import java.io.IOException;
import java.nio.file.Paths;

/** No-cluster executable showing actor-local matching and fail-closed joins. */
public final class OfflineSmoke {
  private OfflineSmoke() {}

  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("events path and scratch directory required");
    ActorRegistry registry = new ActorRegistry();
    Object peer0 = new Object();
    Object peer1 = new Object();
    Object server0 = new Object();
    File snap0 = new File(args[1], "peer0/version-2");
    File snap1 = new File(args[1], "peer1/version-2");
    registry.registerPeer(peer0, 0, snap0, 12001);
    registry.registerPeer(peer1, 1, snap1, 12002);
    registry.registerServer(server0, 0);

    Object verifier = new Object();
    Object creator = new Object();
    registry.registerClient(verifier, "verifier", "verification");
    registry.registerClient(creator, "creatorCloser", "original");
    registry.bindRawSession(verifier, 0x1235L);
    registry.bindRawSession(creator, 0x1234L);

    int applied = 0;
    Probe.io("site.client.write", registry.clientIo(verifier, new Object(), 12001, "write"));
    try {
      Probe.io("site.client.write", registry.clientIo(creator, new Object(), 12001, "write"));
    } catch (IOException expected) { applied++; }

    Probe.io("site.server.read", registry.serverIo(new Object(), new Object(), 0, "read"));
    Probe.io("site.server.read", registry.serverIo(new Object(), server0, 0x1234L, "read"));
    Probe.io("site.file.sync", registry.epochFileIo(peer1,
        new File(snap1, "currentEpoch"), "sync"));
    Probe.io("site.file.sync", registry.epochFileIo(peer0,
        new File(snap0, "unknownName"), "sync"));
    Probe.io("site.file.sync", registry.epochFileIo(peer0,
        new File(snap1, "currentEpoch"), "sync"));
    try {
      Probe.io("site.file.sync", registry.epochFileIo(peer0,
          new File(snap0, "currentEpoch"), "sync"));
    } catch (IOException expected) { applied++; }

    Probe.targetGuard("check.session", registry.target(server0, "leader", 0x1234L), "NORMAL_ARM");
    Probe.write(Paths.get(args[0]));
    if (applied != 2) throw new AssertionError("expected two exact actor-aware faults, got " + applied);
    System.out.println("applied=" + applied);
  }
}
