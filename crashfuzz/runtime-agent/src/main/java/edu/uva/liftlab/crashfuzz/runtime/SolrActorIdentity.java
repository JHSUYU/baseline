package edu.uva.liftlab.crashfuzz.runtime;

import java.lang.reflect.Method;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Stable logical replica identity for SolrCloud's embedded Jetty and workers. */
final class SolrActorIdentity {
    private static final Pattern REPLICA = Pattern.compile("(?:^|\\s)r:([A-Za-z0-9_.-]+)");
    private static final Pattern CORE = Pattern.compile("(?:^|\\s)x:([A-Za-z0-9_.-]+)");
    private static final Pattern VOLATILE_THREAD = Pattern.compile(
            "^(?:qtp[0-9]+-[0-9]+|updateExecutor-[0-9]+-thread-[0-9]+.*|"
                    + "closeThreadPool-[0-9]+-thread-[0-9]+|TEST-.*seed.*)$");

    private SolrActorIdentity() {}

    static ActorIdentity.Resolution resolve(String siteId, String thread) {
        if (!siteId.startsWith("<org.apache.solr.")) {
            return ActorIdentity.Resolution.NOT_APPLICABLE;
        }
        if (!VOLATILE_THREAD.matcher(thread).matches()) {
            return ActorIdentity.Resolution.NOT_APPLICABLE;
        }
        String replica = mdc("replica");
        String core = mdc("core");
        if (core == null && replica == null) {
            core = requestCore();
        }
        return fromContext(thread, replica, core, siteId);
    }

    static ActorIdentity.Resolution fromContext(String thread, String replica,
                                                 String core, String siteId) {
        String role = thread.startsWith("qtp") ? "http" :
                thread.startsWith("updateExecutor-") ? "update" : "worker";
        String logical = value(replica, "r:");
        if (logical == null) logical = token(REPLICA, thread);
        if (logical != null) {
            return new ActorIdentity.Resolution("solr:" + role + ":replica:" + logical,
                    false, null);
        }
        logical = value(core, "x:");
        if (logical == null) logical = token(CORE, thread);
        if (logical != null) {
            return new ActorIdentity.Resolution("solr:" + role + ":core:" + logical,
                    false, null);
        }
        return new ActorIdentity.Resolution("solr:unresolved:" + siteId, true,
                "volatile Solr thread has no replica or core identity");
    }

    private static String token(Pattern pattern, String thread) {
        Matcher match = pattern.matcher(thread);
        return match.find() ? match.group(1) : null;
    }

    private static String value(String raw, String prefix) {
        if (raw == null || raw.isEmpty()) return null;
        return raw.startsWith(prefix) ? raw.substring(prefix.length()) : raw;
    }

    private static String mdc(String key) {
        try {
            ClassLoader loader = Thread.currentThread().getContextClassLoader();
            if (loader == null) loader = SolrActorIdentity.class.getClassLoader();
            Class<?> type = Class.forName("org.slf4j.MDC", false, loader);
            Object result = type.getMethod("get", String.class).invoke(null, key);
            return result instanceof String ? (String) result : null;
        } catch (ReflectiveOperationException | RuntimeException error) {
            return null;
        }
    }

    private static String requestCore() {
        try {
            ClassLoader loader = Thread.currentThread().getContextClassLoader();
            if (loader == null) loader = SolrActorIdentity.class.getClassLoader();
            Class<?> type = Class.forName("org.apache.solr.request.SolrRequestInfo", false, loader);
            Object info = type.getMethod("getRequestInfo").invoke(null);
            if (info == null) return null;
            Object request = info.getClass().getMethod("getReq").invoke(info);
            if (request == null) return null;
            Object core = request.getClass().getMethod("getCore").invoke(request);
            if (core == null) return null;
            Method getName = core.getClass().getMethod("getName");
            Object name = getName.invoke(core);
            return name instanceof String ? (String) name : null;
        } catch (ReflectiveOperationException | RuntimeException error) {
            return null;
        }
    }
}
