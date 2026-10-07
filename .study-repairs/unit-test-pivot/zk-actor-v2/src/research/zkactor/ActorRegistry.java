package research.zkactor;

import java.io.File;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.Map;

/** Per-JVM joins from real I/O receivers to stable test/cluster identities. */
public final class ActorRegistry {
  public static final class IoIdentity {
    public final String actor;
    public final String resource;
    public final String localPeer;
    public final String counterpartyPeer;
    public final String sessionTag;
    public final String unboundReason;

    private IoIdentity(String actor, String resource, String localPeer,
        String counterpartyPeer, String sessionTag, String unboundReason) {
      this.actor = actor;
      this.resource = resource;
      this.localPeer = localPeer;
      this.counterpartyPeer = counterpartyPeer;
      this.sessionTag = sessionTag;
      this.unboundReason = unboundReason;
    }

    public boolean bound() { return unboundReason == null; }
  }

  public static final class TargetIdentity {
    public final String actor;
    public final String role;
    public final String peer;
    public final String sessionTag;
    public final String unboundReason;

    private TargetIdentity(String actor, String role, String peer,
        String sessionTag, String unboundReason) {
      this.actor = actor;
      this.role = role;
      this.peer = peer;
      this.sessionTag = sessionTag;
      this.unboundReason = unboundReason;
    }

    public boolean bound() { return unboundReason == null; }
  }

  private static final class Client {
    final String role;
    final String sessionTag;
    Client(String role, String sessionTag) {
      this.role = role;
      this.sessionTag = sessionTag;
    }
  }

  private static final class Channel {
    final Object client;
    final long peer;
    final int generation;
    Channel(Object client, long peer, int generation) {
      this.client = client;
      this.peer = peer;
      this.generation = generation;
    }
  }

  private static final class ServerConnection {
    final long peer;
    final String sessionTag;
    final int generation;
    ServerConnection(long peer, String sessionTag, int generation) {
      this.peer = peer;
      this.sessionTag = sessionTag;
      this.generation = generation;
    }
  }

  private final IdentityHashMap<Object, Client> clients = new IdentityHashMap<>();
  private final IdentityHashMap<Object, Long> peers = new IdentityHashMap<>();
  private final IdentityHashMap<Object, Long> servers = new IdentityHashMap<>();
  private final IdentityHashMap<Object, Channel> clientChannels = new IdentityHashMap<>();
  private final IdentityHashMap<Object, ServerConnection> serverConnections = new IdentityHashMap<>();
  private final Map<Long, String> sessions = new HashMap<>();
  private final Map<Integer, Long> clientPorts = new HashMap<>();
  private final Map<Path, Long> snapOwners = new HashMap<>();
  private final Map<Long, String> peerRoles = new HashMap<>();
  private final Map<String, Integer> generations = new HashMap<>();

  private static boolean token(String value) {
    return value != null && value.matches("[A-Za-z0-9_.:-]+");
  }

  private static Path path(File file) {
    return file.toPath().toAbsolutePath().normalize();
  }

  private static IoIdentity unbound(String reason) {
    return new IoIdentity(null, null, null, null, null, reason);
  }

  private static TargetIdentity unboundTarget(String reason) {
    return new TargetIdentity(null, null, null, null, reason);
  }

  private int nextGeneration(String key) {
    int next = generations.getOrDefault(key, 0) + 1;
    generations.put(key, next);
    return next;
  }

  public synchronized void registerPeer(Object peer, long sid, File snapDir, int clientPort) {
    if (peer == null || sid < 0 || snapDir == null || clientPort < 0) {
      throw new IllegalArgumentException("peer registration needs receiver, SID, and snapDir");
    }
    Long existingPeer = peers.putIfAbsent(peer, sid);
    if (existingPeer != null && existingPeer.longValue() != sid) {
      throw new IllegalStateException("peer object changed SID");
    }
    Long existingOwner = snapOwners.putIfAbsent(path(snapDir), sid);
    if (existingOwner != null && existingOwner.longValue() != sid) {
      throw new IllegalStateException("snapshot directory has two owners");
    }
    if (clientPort > 0) {
      Long existingPort = clientPorts.putIfAbsent(clientPort, sid);
      if (existingPort != null && existingPort.longValue() != sid) {
        throw new IllegalStateException("client port has two peer owners");
      }
    }
  }

  public synchronized void registerClient(Object client, String role, String sessionTag) {
    if (client == null || !token(role) || !token(sessionTag)) {
      throw new IllegalArgumentException("client needs a stable role and logical session tag");
    }
    Client previous = clients.putIfAbsent(client, new Client(role, sessionTag));
    if (previous != null && (!previous.role.equals(role)
        || !previous.sessionTag.equals(sessionTag))) {
      throw new IllegalStateException("client object changed role/session tag");
    }
  }

  /** A role alias is stable across runs even if election chooses a different physical SID. */
  public synchronized void assignPeerRole(long sid, String role) {
    if (!token(role) || !peers.containsValue(sid)) {
      throw new IllegalArgumentException("peer role needs a registered SID and stable name");
    }
    for (Map.Entry<Long, String> entry : peerRoles.entrySet()) {
      if (entry.getValue().equals(role) && entry.getKey().longValue() != sid) {
        throw new IllegalStateException("role is already assigned to another peer");
      }
    }
    peerRoles.put(sid, role);
  }

  private String peerKey(long sid) {
    String role = peerRoles.get(sid);
    return role == null ? "peer:" + sid : "peer-role:" + role;
  }

  /** Bind the actual ZooKeeperServer receiver to its quorum peer, once known. */
  public synchronized void registerServer(Object server, long sid) {
    if (server == null || sid < 0) {
      throw new IllegalArgumentException("server registration needs receiver and SID");
    }
    Long previous = servers.putIfAbsent(server, sid);
    if (previous != null && previous.longValue() != sid) {
      throw new IllegalStateException("server object changed SID");
    }
  }

  public synchronized void bindRawSession(Object client, long rawSessionId) {
    Client known = clients.get(client);
    if (known == null || rawSessionId == 0) {
      throw new IllegalStateException("raw session has no registered client");
    }
    String old = sessions.putIfAbsent(rawSessionId, known.sessionTag);
    if (old != null && !old.equals(known.sessionTag)) {
      throw new IllegalStateException("raw session maps to conflicting logical sessions");
    }
  }

  /** Call at an actual ClientCnxnSocketNIO I/O receiver with its channel and remote port. */
  public synchronized IoIdentity clientIo(Object client, Object channel, int remotePort,
      String operation) {
    Client c = clients.get(client);
    Long sid = clientPorts.get(remotePort);
    if (c == null || channel == null || sid == null || !token(operation)) {
      return unbound("client-or-channel-or-destination-unbound");
    }
    Channel ch = clientChannels.get(channel);
    if (ch == null) {
      String generationKey = "client:" + c.role + ":" + c.sessionTag + ":" + peerKey(sid);
      ch = new Channel(client, sid, nextGeneration(generationKey));
      clientChannels.put(channel, ch);
    }
    if (ch.client != client || ch.peer != sid) {
      return unbound("channel-owner-or-destination-changed");
    }
    return new IoIdentity("client:" + c.role + ":session:" + c.sessionTag,
        peerKey(sid) + ":channel:" + ch.generation + ":op:" + operation,
        "", Long.toString(sid), c.sessionTag, null);
  }

  /** Server I/O before a session-to-client join is deliberately unbound. */
  public synchronized IoIdentity serverIo(Object connection, Object server,
      long rawSessionId, String operation) {
    Long localSid = servers.get(server);
    String tag = sessions.get(rawSessionId);
    if (connection == null || localSid == null || rawSessionId == 0
        || tag == null || !token(operation)) {
      return unbound("server-connection-or-session-unbound");
    }
    ServerConnection c = serverConnections.get(connection);
    if (c == null) {
      String generationKey = "server:" + peerKey(localSid) + ":session:" + tag;
      c = new ServerConnection(localSid, tag, nextGeneration(generationKey));
      serverConnections.put(connection, c);
    }
    if (c.peer != localSid.longValue() || !c.sessionTag.equals(tag)) {
      return unbound("server-connection-owner-changed");
    }
    return new IoIdentity(peerKey(localSid) + ":session:" + tag,
        "connection:" + c.generation + ":op:" + operation,
        Long.toString(localSid), "", tag, null);
  }

  /** Peer-owned epoch file I/O, including nested AtomicFileOutputStream.origFile. */
  public synchronized IoIdentity epochFileIo(Object peer, File actualFile, String operation) {
    Long receiverSid = peers.get(peer);
    if (receiverSid == null) return unbound("quorum-peer-receiver-unbound");
    IoIdentity fromFile = epochFileIo(actualFile, operation);
    if (!fromFile.bound() || !fromFile.localPeer.equals(Long.toString(receiverSid))) {
      return unbound("epoch-file-owner-does-not-match-peer-receiver");
    }
    return fromFile;
  }

  public synchronized IoIdentity epochFileIo(File actualFile, String operation) {
    if (actualFile == null || !token(operation)) return unbound("epoch-file-unbound");
    Path normalized = path(actualFile);
    String filename = normalized.getFileName().toString();
    if (!filename.equals("currentEpoch") && !filename.equals("acceptedEpoch")
        && !filename.equals("currentEpoch.tmp") && !filename.equals("acceptedEpoch.tmp")) {
      return unbound("not-a-known-epoch-file");
    }
    Long sid = snapOwners.get(normalized.getParent());
    if (sid == null) return unbound("epoch-file-owner-unbound");
    return new IoIdentity(peerKey(sid), "file:" + filename + ":op:" + operation,
        Long.toString(sid), "", "", null);
  }

  public synchronized TargetIdentity target(Object peer, String role, long rawSessionId) {
    Long sid = peers.get(peer);
    if (sid == null) sid = servers.get(peer);
    if (sid == null || !token(role)) return unboundTarget("target-peer-or-role-unbound");
    String sessionTag = rawSessionId == 0 ? "" : sessions.get(rawSessionId);
    if (rawSessionId != 0 && sessionTag == null) {
      return unboundTarget("target-session-unbound");
    }
    return new TargetIdentity(peerKey(sid), role, Long.toString(sid), sessionTag, null);
  }
}
