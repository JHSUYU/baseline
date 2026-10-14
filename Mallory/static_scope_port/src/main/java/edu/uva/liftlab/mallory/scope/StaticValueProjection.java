package edu.uva.liftlab.mallory.scope;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.zip.GZIPInputStream;

/** Projects selected GraphChecker value transfers into region-level MAY hints. */
final class StaticValueProjection {
    private StaticValueProjection() {}

    static List<JsonObject> read(Path directory, Map<String, Set<String>> regionsByMethod)
            throws IOException {
        Path path = directory.resolve("candidate_dataflow_edges.jsonl.gz");
        List<JsonObject> rows = new ArrayList<>();
        Set<String> seen = new LinkedHashSet<>();
        Set<String> usedMethods = new LinkedHashSet<>();
        try (BufferedReader input = new BufferedReader(new InputStreamReader(
                new GZIPInputStream(Files.newInputStream(path)), StandardCharsets.UTF_8))) {
            String line;
            while ((line = input.readLine()) != null) {
                if (line.trim().isEmpty()) continue;
                JsonObject edge = JsonParser.parseString(line).getAsJsonObject();
                String edgeKind = value(edge, "kind");
                String transfer = value(edge, "transferKind");
                if (transfer.isEmpty()) throw new IOException(
                        "GraphChecker candidate edge lacks transferKind: " + path);
                if (!("VALUE_TRANSFER".equals(transfer)
                        || "VALUE_PASS".equals(transfer)
                        || "DYNAMIC_DISPATCH".equals(transfer)
                        && !"dispatch_activation".equals(edgeKind))) continue;
                String producer = method(value(edge, "fromCell"));
                String consumer = method(value(edge, "toCell"));
                if (producer.equals(consumer)
                        || !regionsByMethod.containsKey(producer)
                        || !regionsByMethod.containsKey(consumer)) continue;
                String key = producer + "\n" + consumer + "\n" + edgeKind;
                if (!seen.add(key)) continue;
                JsonObject row = new JsonObject();
                row.addProperty("schemaVersion", 1);
                row.addProperty("kind", "STATIC_SCOPE_SITE");
                row.addProperty("role", "STATIC_VALUE_EDGE");
                row.addProperty("producerMethod", producer);
                row.addProperty("consumerMethod", consumer);
                row.addProperty("carrier", edgeKind);
                row.addProperty("siteId", value(edge, "siteId"));
                row.addProperty("staticMayOnly", true);
                rows.add(row);
                usedMethods.add(producer);
                usedMethods.add(consumer);
            }
        }
        for (String method : usedMethods) {
            for (String region : regionsByMethod.getOrDefault(method,
                    Collections.<String>emptySet())) {
                JsonObject row = new JsonObject();
                row.addProperty("schemaVersion", 1);
                row.addProperty("kind", "STATIC_SCOPE_SITE");
                row.addProperty("role", "STATIC_REGION_METHOD");
                row.addProperty("regionId", region);
                row.addProperty("vmMethod", method);
                row.addProperty("staticMayOnly", true);
                rows.add(row);
            }
        }
        return rows;
    }

    private static String method(String cell) {
        if (!cell.startsWith("<")) return "";
        int end = cell.indexOf('>');
        if (end < 0) return "";
        String signature = cell.substring(0, end + 1);
        return signature.indexOf('(') > 0 ? signature : "";
    }

    private static String value(JsonObject row, String field) {
        return row.has(field) && !row.get(field).isJsonNull()
                ? row.get(field).getAsString() : "";
    }
}
