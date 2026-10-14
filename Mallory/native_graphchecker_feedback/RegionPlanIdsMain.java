package edu.uva.liftlab.mallory.nativefeedback;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import edu.uva.liftlab.graphchecker.contract.OccurrenceAddress;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

/** Resolve original Finalizer plan addresses through GraphChecker identity. */
public final class RegionPlanIdsMain {
    private RegionPlanIdsMain() { }

    public static void main(String[] args) throws Exception {
        if (args.length != 1) {
            throw new IllegalArgumentException("expected original plan JSONL path");
        }
        Path plan = Paths.get(args[0]);
        JsonParser parser = new JsonParser();
        for (String line : Files.readAllLines(plan, StandardCharsets.UTF_8)) {
            if (line.trim().isEmpty()) continue;
            JsonObject row = parser.parse(line).getAsJsonObject();
            if (!"CONCOLIC_REGION_PLAN".equals(row.get("kind").getAsString())) {
                continue;
            }
            String address = row.get("occurrenceId").getAsString();
            System.out.println(OccurrenceAddress.parse(address).id() + "\t" + address);
        }
    }
}
