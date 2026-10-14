package edu.uva.liftlab.mallory.graphchecker.runtime;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Deque;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Conservative static relevance. A MAY relation is never an observed edge. */
final class StaticScope {
    private final List<JsonObject> rows;
    private final Map<String, List<JsonObject>> reads = new HashMap<>();
    private final Map<String, List<JsonObject>> imports = new HashMap<>();
    private final Map<String, List<JsonObject>> writers = new HashMap<>();
    private final Map<String, List<JsonObject>> exporters = new HashMap<>();
    private final Map<String, List<JsonObject>> doors = new HashMap<>();
    private final Map<String, Set<String>> methodsByRegion = new HashMap<>();
    private final Map<String, Set<String>> regionsByMethod = new HashMap<>();
    private final Map<String, List<JsonObject>> valueEdgesByConsumerMethod = new HashMap<>();
    private final Map<String, String> targets = new HashMap<>();

    private StaticScope(List<JsonObject> rows) {
        this.rows = rows;
        for (JsonObject row : rows) {
            String role = value(row, "role");
            String region = value(row, "regionId");
            if ("STATIC_VALUE_EDGE".equals(role)) {
                put(valueEdgesByConsumerMethod, value(row, "consumerMethod"), row);
                continue;
            }
            if (region.isEmpty()) continue;
            if ("STATIC_REGION_METHOD".equals(role)) {
                String method = value(row, "vmMethod");
                if (!method.isEmpty()) {
                    methodsByRegion.computeIfAbsent(region,
                            unused -> new LinkedHashSet<>()).add(method);
                    regionsByMethod.computeIfAbsent(method,
                            unused -> new LinkedHashSet<>()).add(region);
                }
                continue;
            }
            if ("READ_SITE".equals(role)) put(reads, region, row);
            else if ("IMPORT_SITE".equals(role)) put(imports, region, row);
            else if ("WRITE_SITE".equals(role)) put(writers, value(row, "cell"), row);
            else if ("EXPORT_SITE".equals(role)) put(exporters, value(row, "portId"), row);
            else if ("DOOR_SITE".equals(role)) put(doors, region, row);
            else if ("TARGET_SITE".equals(role) || "THROW_SITE".equals(role)) {
                targets.put(value(row, "siteId"), region);
            }
        }
    }

    static StaticScope read(Path path) throws IOException {
        List<JsonObject> rows = new ArrayList<>();
        for (String line : Files.readAllLines(path, StandardCharsets.UTF_8)) {
            if (line.trim().isEmpty()) continue;
            JsonObject row = new JsonParser().parse(line).getAsJsonObject();
            if (!"STATIC_SCOPE_SITE".equals(value(row, "kind"))) {
                throw new IllegalArgumentException("invalid static scope row: " + path);
            }
            rows.add(row);
        }
        if (rows.isEmpty()) throw new IllegalArgumentException("empty static scope map: " + path);
        return new StaticScope(rows);
    }

    Result mayReach(String targetSite, Set<String> observedClosureRegions) {
        String targetRegion = targets.get(targetSite);
        if (targetRegion == null || targetRegion.isEmpty()) {
            return new Result(false, Collections.<String>emptySet(),
                    Collections.<String>emptySet(), Collections.<JsonObject>emptyList());
        }
        Set<String> regions = new LinkedHashSet<>();
        Deque<String> pending = new ArrayDeque<>();
        regions.add(targetRegion);
        pending.add(targetRegion);
        for (String region : observedClosureRegions) {
            if (!region.isEmpty() && regions.add(region)) pending.add(region);
        }
        List<JsonObject> relations = new ArrayList<>();
        Set<String> relationKeys = new LinkedHashSet<>();
        Set<String> valueWitnesses = new LinkedHashSet<>();
        while (!pending.isEmpty()) {
            String consumer = pending.removeFirst();
            for (JsonObject read : reads.getOrDefault(consumer, Collections.<JsonObject>emptyList())) {
                String cell = value(read, "cell");
                for (JsonObject write : writers.getOrDefault(cell, Collections.<JsonObject>emptyList())) {
                    addMay("STATIC_STATE", cell, write, read, regions, pending,
                            relations, relationKeys);
                }
            }
            for (JsonObject in : imports.getOrDefault(consumer, Collections.<JsonObject>emptyList())) {
                String port = value(in, "portId");
                for (JsonObject out : exporters.getOrDefault(port, Collections.<JsonObject>emptyList())) {
                    addMay("STATIC_WIRE", port, out, in, regions, pending,
                            relations, relationKeys);
                }
            }
            for (String method : methodsByRegion.getOrDefault(consumer,
                    Collections.<String>emptySet())) {
                for (JsonObject edge : valueEdgesByConsumerMethod.getOrDefault(method,
                        Collections.<JsonObject>emptyList())) {
                    for (String from : regionsByMethod.getOrDefault(
                            value(edge, "producerMethod"), Collections.<String>emptySet())) {
                        if (from.equals(consumer)) continue;
                        if (valueWitnesses.add(from)) {
                            JsonObject relation = new JsonObject();
                            relation.addProperty("kind", "STATIC_VALUE");
                            relation.addProperty("carrier", value(edge, "carrier"));
                            relation.addProperty("producerMethod",
                                    value(edge, "producerMethod"));
                            relation.addProperty("consumerMethod", method);
                            relation.addProperty("producerRegionId", from);
                            relation.addProperty("consumerRegionId", consumer);
                            relation.addProperty("staticMayOnly", true);
                            relations.add(relation);
                        }
                        if (regions.add(from)) pending.add(from);
                    }
                }
            }
        }
        Set<String> doorSites = new LinkedHashSet<>();
        for (String region : regions) {
            for (JsonObject door : doors.getOrDefault(region, Collections.<JsonObject>emptyList())) {
                doorSites.add(value(door, "siteId"));
            }
        }
        doorSites.remove("");
        return new Result(true, regions, doorSites, relations);
    }

    private static void addMay(String kind, String carrier, JsonObject producer,
                               JsonObject consumer, Set<String> regions,
                               Deque<String> pending, List<JsonObject> relations,
                               Set<String> keys) {
        String from = value(producer, "regionId");
        String to = value(consumer, "regionId");
        if (from.isEmpty() || to.isEmpty()) return;
        String key = kind + "\n" + carrier + "\n" + value(producer, "siteId")
                + "\n" + value(consumer, "siteId");
        if (keys.add(key)) {
            JsonObject relation = new JsonObject();
            relation.addProperty("kind", kind);
            relation.addProperty("carrier", carrier);
            relation.addProperty("producerRegionId", from);
            relation.addProperty("producerSiteId", value(producer, "siteId"));
            relation.addProperty("consumerRegionId", to);
            relation.addProperty("consumerSiteId", value(consumer, "siteId"));
            relations.add(relation);
        }
        if (regions.add(from)) pending.add(from);
    }

    private static void put(Map<String, List<JsonObject>> map, String key, JsonObject row) {
        if (!key.isEmpty()) map.computeIfAbsent(key, unused -> new ArrayList<>()).add(row);
    }

    private static String value(JsonObject row, String field) {
        return row.has(field) && !row.get(field).isJsonNull()
                ? row.get(field).getAsString() : "";
    }

    static final class Result {
        final boolean targetFound;
        final Set<String> regions;
        final Set<String> doorSites;
        final List<JsonObject> relations;

        Result(boolean targetFound, Set<String> regions, Set<String> doorSites,
               List<JsonObject> relations) {
            this.targetFound = targetFound;
            this.regions = regions;
            this.doorSites = doorSites;
            this.relations = relations;
        }
    }
}
