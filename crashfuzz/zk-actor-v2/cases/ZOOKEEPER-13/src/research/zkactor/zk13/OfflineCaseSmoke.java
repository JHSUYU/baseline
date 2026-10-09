package research.zkactor.zk13;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.List;
import research.zkactor.ActorRegistry;
import research.zkactor.Probe;

/** Confirm selectors cannot fire on another client, destination, or session. */
public final class OfflineCaseSmoke {
  public static void main(String[] args) throws Exception {
    ActorRegistry registry = new ActorRegistry();
    Object peer1 = new Object(), peer2 = new Object(), client = new Object();
    registry.registerPeer(peer1, 1, new File(args[0], "peer1"), 12001);
    registry.registerPeer(peer2, 2, new File(args[0], "peer2"), 12002);
    registry.registerClient(client, "initialGlobalClient", "initialGlobalSession");
    registry.bindRawSession(client, 0x1234L);
    Object channel = new Object();
    String site = "ClientCnxnSocketNIO#doIO:119:SocketChannel.write";
    Probe.io(site, registry.clientIo(new Object(), channel, 12001, "write"));
    Probe.io(site, registry.clientIo(client, channel, 12001, "write"));
    Probe.io(site, registry.clientIo(client, channel, 12002, "write"));
    int applied = 0;
    try { Probe.io(site, registry.clientIo(client, channel, 12001, "write")); }
    catch (IOException expected) { applied++; }
    Object server = new Object();
    registry.registerServer(server, 1);
    Probe.targetGuard(Bridge.CHECK, registry.target(server, "readOnlyPeer1", 0x1234L), "global");
    Probe.targetGuard(Bridge.CHECK, registry.target(server, "readOnlyPeer1", 0x9999L), "global");
    Probe.write(Paths.get(args[1]));
    List<String> rows = Files.readAllLines(Paths.get(args[1]));
    long matched = rows.stream().filter(row -> row.contains("\tFAULT_MATCHED\t")).count();
    long unbound = rows.stream().filter(row -> row.contains("\tUNBOUND_IO\t")).count();
    long guards = rows.stream().filter(row -> row.contains("\tTARGET_GUARD\t")).count();
    long unboundTarget = rows.stream().filter(row -> row.contains("\tUNBOUND_TARGET\t")).count();
    if (applied != 1 || matched != 1 || unbound != 2 || guards != 1 || unboundTarget != 1) {
      throw new AssertionError("wrong actor admitted or selected actor rejected: "
          + applied + "/" + matched + "/" + unbound + "/" + guards + "/" + unboundTarget);
    }
    System.out.println("zk13_wrong_actor_smoke=pass applied=" + applied);
  }
}
