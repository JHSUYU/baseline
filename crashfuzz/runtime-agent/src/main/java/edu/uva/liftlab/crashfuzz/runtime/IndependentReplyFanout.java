package edu.uva.liftlab.crashfuzz.runtime;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

import java.util.HashSet;
import java.util.Set;

/** Recognizes one unordered set of equivalent replies to distinct nodes. */
final class IndependentReplyFanout {
    private IndependentReplyFanout() {}

    static boolean enabled(JsonArray faults) {
        if (faults == null || faults.size() < 2) return false;
        JsonObject first = faults.get(0).getAsJsonObject();
        String shape = value(first, "responseShape");
        if (!"after".equals(value(first, "phase")) || !hasObjectArrayElement(shape)) {
            return false;
        }
        Set<String> nodes = new HashSet<>();
        for (int index = 0; index < faults.size(); index++) {
            JsonObject fault = faults.get(index).getAsJsonObject();
            if (!"after".equals(value(fault, "phase"))
                    || !shape.equals(value(fault, "responseShape"))
                    || !value(first, "marker").equals(value(fault, "marker"))
                    || !value(first, "siteId").equals(value(fault, "siteId"))
                    || !value(first, "sourceKey").equals(value(fault, "sourceKey"))
                    || !value(first, "exceptionClass").equals(value(fault, "exceptionClass"))) {
                return false;
            }
            String occurrence = value(fault, "occurrence");
            int suffix = occurrence.lastIndexOf("/<");
            int separator = occurrence.lastIndexOf('|', suffix);
            if (suffix < 0 || separator < 0 || separator + 1 == suffix
                    || !nodes.add(occurrence.substring(separator + 1, suffix))) {
                return false;
            }
        }
        return true;
    }

    private static boolean hasObjectArrayElement(String shape) {
        String[] fields = shape.split("\\|");
        for (int index = 1; index < fields.length; index++) {
            int start = fields[index].indexOf("=[");
            if (start >= 0 && start + 2 < fields[index].length()
                    && fields[index].charAt(start + 2) != ']') return true;
        }
        return false;
    }

    private static String value(JsonObject object, String key) {
        return object.has(key) && !object.get(key).isJsonNull()
                ? object.get(key).getAsString() : "";
    }
}
