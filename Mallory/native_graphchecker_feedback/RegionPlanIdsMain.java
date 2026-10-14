package edu.uva.liftlab.mallory.nativefeedback;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.google.gson.JsonElement;
import com.google.gson.Gson;
import com.google.gson.TypeAdapter;
import com.google.gson.stream.JsonReader;
import edu.uva.liftlab.graphchecker.contract.OccurrenceAddress;

import java.io.BufferedReader;
import java.io.StringReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

/** Resolve original Finalizer plan addresses through GraphChecker identity. */
public final class RegionPlanIdsMain {
    private RegionPlanIdsMain() { }

    public static void main(String[] args) throws Exception {
        boolean project = args.length == 2 && "--project".equals(args[0]);
        if (!project && args.length != 1) {
            throw new IllegalArgumentException("expected [--project] original plan JSONL path");
        }
        Path plan = Paths.get(args[project ? 1 : 0]);
        JsonParser parser = new JsonParser();
        TypeAdapter<JsonElement> values = new Gson().getAdapter(JsonElement.class);
        try (BufferedReader lines = Files.newBufferedReader(
                plan, StandardCharsets.UTF_8)) {
            String line;
            while ((line = lines.readLine()) != null) {
                if (line.trim().isEmpty()) continue;
                if (project) {
                    System.out.println(project(line, values));
                } else {
                    JsonObject row = parser.parse(line).getAsJsonObject();
                    if (!"CONCOLIC_REGION_PLAN".equals(
                            row.get("kind").getAsString())) continue;
                    String address = row.get("occurrenceId").getAsString();
                    System.out.println(OccurrenceAddress.parse(address).id()
                            + "\t" + address);
                }
            }
        }
    }

    /** Read only the fields consumed by the Python summary.  In particular,
     * skip each plan's large closureGoals without building its object tree. */
    private static JsonObject project(String line,
            TypeAdapter<JsonElement> values) throws Exception {
        JsonObject selected = new JsonObject();
        int gaps = 0;
        try (JsonReader reader = new JsonReader(new StringReader(line))) {
            reader.beginObject();
            while (reader.hasNext()) {
                String field = reader.nextName();
                if ("gaps".equals(field)) {
                    reader.beginArray();
                    while (reader.hasNext()) {
                        reader.skipValue();
                        gaps++;
                    }
                    reader.endArray();
                } else if ("kind".equals(field)
                        || "occurrenceId".equals(field)
                        || "regionId".equals(field)
                        || "sourceKey".equals(field)
                        || "rootCallId".equals(field)
                        || "foldedRegionIds".equals(field)
                        || "admissionBasis".equals(field)
                        || "demandDepth".equals(field)) {
                    selected.add(field, values.read(reader));
                } else {
                    reader.skipValue();
                }
            }
            reader.endObject();
        }
        if ("CONCOLIC_RUNTIME_MODEL_CATALOG".equals(
                selected.get("kind").getAsString())) {
            selected.addProperty("catalogGaps", gaps);
        } else if ("CONCOLIC_REGION_PLAN".equals(
                selected.get("kind").getAsString())) {
            String address = selected.get("occurrenceId").getAsString();
            selected.addProperty("graphCheckerId",
                    OccurrenceAddress.parse(address).id());
        }
        return selected;
    }
}
