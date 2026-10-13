package edu.uva.liftlab.crashfuzz.runtime;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.IdentityHashMap;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Logical node identity for selected actor instances in embedded clusters. */
final class ActorIdentity {
    private static final String BP_ACTOR =
            "org.apache.hadoop.hdfs.server.datanode.BPServiceActor";
    private static final String DATA_XCEIVER =
            "org.apache.hadoop.hdfs.server.datanode.DataXceiver";
    private static final String DATA_TRANSFER =
            "org.apache.hadoop.hdfs.server.datanode.DataNode$DataTransfer";
    private static final String DATA_DIR_KEY = "dfs.datanode.data.dir";
    private static final Pattern MINI_DFS_SLOT = Pattern.compile(
            "/data/dfs/data/(data[0-9]+)(?=,|/|$)");
    private static final Map<Object, Resolution> CACHE = new IdentityHashMap<>();
    private static final ThreadLocal<Resolution> CURRENT_ACTOR = new ThreadLocal<>();
    private static int nextUnknown;

    private ActorIdentity() {}

    static final class Resolution {
        static final Resolution NOT_APPLICABLE = new Resolution(null, false, null);
        final String logicalNodeId;
        final boolean gap;
        final String reason;

        Resolution(String logicalNodeId, boolean gap, String reason) {
            this.logicalNodeId = logicalNodeId;
            this.gap = gap;
            this.reason = reason;
        }

        boolean applies() { return logicalNodeId != null; }
    }

    static Resolution resolve(Object owner) {
        if (owner == null) {
            return Resolution.NOT_APPLICABLE;
        }
        String dataNodeField = dataNodeField(owner.getClass());
        if (dataNodeField == null) return Resolution.NOT_APPLICABLE;
        synchronized (CACHE) {
            Resolution cached = CACHE.get(owner);
            if (cached != null) return cached;
            String slot = hdfsMiniDataNodeSlot(owner, dataNodeField);
            Resolution result = slot == null
                    ? new Resolution("hdfs:dn:unknown#" + ++nextUnknown, true,
                            "dfs.datanode.data.dir has no MiniDFSCluster dataN slot")
                    : new Resolution("hdfs:dn:" + slot, false, null);
            CACHE.put(owner, result);
            return result;
        }
    }

    static Resolution resolve(Object owner, String siteId, String thread) {
        Resolution hdfs = resolve(owner);
        if (hdfs.applies()) return hdfs;
        Resolution current = CURRENT_ACTOR.get();
        return current != null ? current : SolrActorIdentity.resolve(owner, siteId, thread);
    }

    static void bindCurrentThread(Object owner) {
        Resolution resolution = resolve(owner);
        if (resolution.applies()) CURRENT_ACTOR.set(resolution);
    }

    static void clearCurrentThread() { CURRENT_ACTOR.remove(); }

    static Resolution currentThread() {
        Resolution current = CURRENT_ACTOR.get();
        return current == null ? Resolution.NOT_APPLICABLE : current;
    }

    private static String dataNodeField(Class<?> type) {
        for (Class<?> current = type; current != null; current = current.getSuperclass()) {
            if (BP_ACTOR.equals(current.getName())) return "dn";
            if (DATA_XCEIVER.equals(current.getName())) return "datanode";
            if (DATA_TRANSFER.equals(current.getName())) return "this$0";
        }
        return null;
    }

    private static String hdfsMiniDataNodeSlot(Object actor, String dataNodeField) {
        try {
            Field dnField = null;
            for (Class<?> type = actor.getClass(); type != null; type = type.getSuperclass()) {
                try {
                    dnField = type.getDeclaredField(dataNodeField);
                    break;
                } catch (NoSuchFieldException ignored) {
                    // The actor may be an instrumented subclass.
                }
            }
            if (dnField == null) return null;
            dnField.setAccessible(true);
            Object dn = dnField.get(actor);
            if (dn == null) return null;
            Method getConf = dn.getClass().getMethod("getConf");
            Object conf = getConf.invoke(dn);
            if (conf == null) return null;
            Method get = conf.getClass().getMethod("get", String.class);
            Object raw = get.invoke(conf, DATA_DIR_KEY);
            if (!(raw instanceof String)) return null;
            Matcher match = MINI_DFS_SLOT.matcher((String) raw);
            return match.find() ? match.group(1) : null;
        } catch (ReflectiveOperationException | RuntimeException error) {
            return null;
        }
    }
}
