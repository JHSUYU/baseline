package edu.uva.liftlab.graphchecker.plan;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.BufferedReader;
import java.lang.management.ManagementFactory;
import java.lang.management.ThreadMXBean;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.List;

/** Read-only differential/performance probe. Put either a frozen engine JAR
 * or the new engine classes first on its runtime classpath. */
public final class StaticScopeMapDeclaredTraceProbe {
    private StaticScopeMapDeclaredTraceProbe() {}

    private static String text(JsonObject row, String key) {
        return row.has(key) && !row.get(key).isJsonNull()
                ? row.get(key).getAsString() : "";
    }

    private static void digest(MessageDigest hash, String value) {
        hash.update((value + "\u0000").getBytes(StandardCharsets.UTF_8));
    }

    private static String hex(byte[] bytes) {
        StringBuilder result = new StringBuilder();
        for (byte value : bytes) result.append(String.format("%02x", value & 0xff));
        return result.toString();
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            throw new IllegalArgumentException("usage: StaticScopeMapDeclaredTraceProbe map.jsonl runtime_trace.jsonl");
        }
        Path mapFile = Paths.get(args[0]);
        Path traceFile = Paths.get(args[1]);
        long started = System.nanoTime();
        StaticScopeMap map = StaticScopeMap.read(mapFile);
        long readNanos = System.nanoTime() - started;
        List<String[]> queries = new ArrayList<>();
        try (BufferedReader input = Files.newBufferedReader(traceFile,
                StandardCharsets.UTF_8)) {
            for (String line; (line = input.readLine()) != null;) {
                JsonObject row = JsonParser.parseString(line).getAsJsonObject();
                if ("CALL_SITE_ENTER".equals(text(row, "event"))) {
                    queries.add(new String[]{text(row, "siteId"),
                            text(row, "declaredCallee")});
                }
            }
        }
        MessageDigest hash = MessageDigest.getInstance("SHA-256");
        int matched = 0;
        int sites = 0;
        ThreadMXBean thread = ManagementFactory.getThreadMXBean();
        long cpuStarted = thread.isCurrentThreadCpuTimeSupported()
                ? thread.getCurrentThreadCpuTime() : -1;
        started = System.nanoTime();
        for (String[] query : queries) {
            List<StaticScopeMap.Site> found = map.declaredSitesAt(query[0], query[1]);
            if (!found.isEmpty()) matched++;
            sites += found.size();
            digest(hash, Integer.toString(found.size()));
            for (StaticScopeMap.Site site : found) {
                digest(hash, site.role);
                digest(hash, site.regionId);
                digest(hash, site.siteId);
                digest(hash, site.declaredCallee);
                digest(hash, site.cell);
                digest(hash, site.declared.kind);
                digest(hash, site.declared.edgeId);
                digest(hash, site.declared.dependencyCell);
            }
        }
        long lookupNanos = System.nanoTime() - started;
        long cpuNanos = cpuStarted < 0 ? -1
                : thread.getCurrentThreadCpuTime() - cpuStarted;
        System.out.println("map_read_ms=" + (readNanos / 1_000_000L)
                + " queries=" + queries.size() + " matched=" + matched
                + " returned_sites=" + sites
                + " lookup_ms=" + (lookupNanos / 1_000_000L)
                + " lookup_cpu_ms=" + (cpuNanos / 1_000_000L)
                + " output_sha256=" + hex(hash.digest()));
    }
}
