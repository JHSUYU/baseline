package edu.uva.liftlab.graphchecker.runtime;

import edu.uva.liftlab.graphchecker.contract.Role;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Identity boundary for one inbound HDFS data-transfer SASL request.
 *
 * The DataNode thread may inherit the embedded JUnit client's root.  A new
 * root per accepted request makes the two encrypted reads addressable without
 * changing Hadoop's request bytes or the test's operations.  The adapter is
 * intentionally small: transport payload propagation remains a separate
 * obligation and is never inferred from this request root alone.
 */
public final class HdfsSaslRequestIdentity {
    private static final ConcurrentHashMap<String, String> LOGICAL_NODES =
            new ConcurrentHashMap<>();
    private static final AtomicInteger NEXT_NODE = new AtomicInteger();
    private static final AtomicInteger NEXT_EXCHANGE = new AtomicInteger();
    private static final ConcurrentHashMap<String, Pending> PENDING =
            new ConcurrentHashMap<>();
    private static final ThreadLocal<String> CLIENT_ENDPOINT = new ThreadLocal<>();
    private static final ThreadLocal<ServerEndpoint> SERVER_ENDPOINT =
            new ThreadLocal<>();
    private HdfsSaslRequestIdentity() {
    }

    public static final class Scope {
        private final long lineage;
        private final long request;
        private final String api;
        private final AtomicBoolean ended = new AtomicBoolean();
        private final boolean sasl;

        private Scope(long lineage, long request, String api, boolean sasl) {
            this.lineage = lineage;
            this.request = request;
            this.api = api;
            this.sasl = sasl;
        }
    }

    private static final class Pending {
        private final MessageDoors.Outbound outbound;
        private final String userName;

        private Pending(MessageDoors.Outbound outbound, String userName) {
            this.outbound = outbound;
            this.userName = userName;
        }
    }

    private static final class ServerEndpoint {
        private final Object server;
        private final String endpoint;

        private ServerEndpoint(Object server, String endpoint) {
            this.server = server;
            this.endpoint = endpoint;
        }
    }

    public static Scope enter(Object server, String datanodeUuid) {
        return enter(server, datanodeUuid, "SASL_DATA_TRANSFER", null);
    }

    public static Scope enter(Object server, String datanodeUuid, String api) {
        return enter(server, datanodeUuid, api, null);
    }

    public static Scope enter(Object server, String datanodeUuid, String api,
                              String remoteEndpoint) {
        if (server == null || datanodeUuid == null
                || datanodeUuid.isEmpty() || api == null || api.isEmpty()) {
            throw new IllegalArgumentException(
                    "DataNode request requires owner, UUID, and API");
        }
        // The UUID is regenerated when this embedded cluster is rebuilt in
        // a fresh scratch directory.  The one-DataNode owner fixture has a
        // stable logical slot: first observed DataNode is slot 0.  Map each
        // UUID once so repeated registration and SASL callbacks keep it.
        String sourceId = LOGICAL_NODES.computeIfAbsent(datanodeUuid,
                ignored -> "hdfs/datanode/" + NEXT_NODE.getAndIncrement());
        MessageDoors.registerSource(server, "HDFS_DATANODE", "DATANODE",
                sourceId, 0L);
        long lineage = Lineage.pushCallRoot(sourceId + "#epoch0",
                Role.of("DATANODE"), api);
        try {
            long request = MessageDoors.beginRequest(server, api);
            boolean sasl = "SASL_DATA_TRANSFER".equals(api);
            if (sasl) {
                SERVER_ENDPOINT.set(new ServerEndpoint(server, remoteEndpoint));
            }
            return new Scope(lineage, request, api, sasl);
        } catch (RuntimeException | Error failure) {
            Lineage.pop(lineage);
            throw failure;
        }
    }

    public static void exit(Scope scope) {
        if (scope == null || !scope.ended.compareAndSet(false, true)) return;
        try {
            MessageDoors.endRequest(scope.request, scope.api);
        } finally {
            if (scope.sasl) SERVER_ENDPOINT.remove();
            Lineage.pop(scope.lineage);
        }
    }

    /** Pair one actual TCP connection inside the unchanged MiniDFSCluster. */
    public static void clientEndpoint(String address) {
        if (address != null) CLIENT_ENDPOINT.set(address);
    }

    public static void clearClientEndpoint() {
        CLIENT_ENDPOINT.remove();
    }

    /** Called on the normal path immediately before writing SASL bytes. */
    public static void clientSend(String userName) {
        String endpoint = CLIENT_ENDPOINT.get();
        if (endpoint == null || userName == null) return;
        String correlation = "hdfs11-sasl-" + NEXT_EXCHANGE.incrementAndGet();
        MessageDoors.Outbound outgoing = MessageDoors.outbound("HDFS_SASL",
                correlation, "1", MessageDoors.REQUEST, null, null, userName);
        if (outgoing.active()) PENDING.put(endpoint, new Pending(outgoing, userName));
    }

    /** Called after the received SASL name reaches the server-side parser. */
    public static void serverReceive(String userName) {
        ServerEndpoint server = SERVER_ENDPOINT.get();
        if (server == null || server.endpoint == null) return;
        Pending pending = PENDING.remove(server.endpoint);
        if (pending == null) {
            System.err.println("[HDFS11_SASL_ADAPTER] missing outbound for received name");
            return;
        }
        if (!pending.userName.equals(userName)) {
            System.err.println("[HDFS11_SASL_ADAPTER] received name differs from paired outbound");
            return;
        }
        MessageDoors.inbound(pending.outbound.trace, pending.outbound.symbolic,
                "HDFS_SASL", pending.outbound.correlationId,
                pending.outbound.attemptId, MessageDoors.REQUEST,
                server.server, false);
    }
}
