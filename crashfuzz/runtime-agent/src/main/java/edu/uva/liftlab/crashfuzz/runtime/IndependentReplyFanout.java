package edu.uva.liftlab.crashfuzz.runtime;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;

import java.util.HashSet;
import java.util.Set;

/**
 * Recognizes a plan whose faults have no order of their own: one unordered set of
 * equivalent replies to distinct nodes, or of one call each distinct node makes
 * for the same event (every node's watch on one changed store node fires
 * concurrently, so which fires first is a race, not part of the plan).
 */
final class IndependentReplyFanout {
    private IndependentReplyFanout() {}

    static boolean enabled(JsonArray faults) {
        return replyFanout(faults) || concurrentCalls(faults);
    }

    /** Faults before one call site, each on a distinct logical node. */
    static boolean concurrentCalls(JsonArray faults) {
        if (faults == null || faults.size() < 2) return false;
        JsonObject first = faults.get(0).getAsJsonObject();
        Set<String> nodes = new HashSet<>();
        for (int index = 0; index < faults.size(); index++) {
            JsonObject fault = faults.get(index).getAsJsonObject();
            if (!"".equals(value(fault, "phase")) && !"before".equals(value(fault, "phase"))
                    || !value(first, "marker").equals(value(fault, "marker"))
                    || !value(first, "siteId").equals(value(fault, "siteId"))
                    || !value(first, "sourceKey").equals(value(fault, "sourceKey"))
                    || !value(first, "exceptionClass").equals(value(fault, "exceptionClass"))) {
                return false;
            }
            if (!nodes.add(logicalNode(value(fault, "occurrence")))) return false;
        }
        return true;
    }

    /** The logical node of an occurrence: its actor's |node suffix, else the actor. */
    static String logicalNode(String occurrence) {
        int suffix = occurrence.lastIndexOf("/<");
        int start = occurrence.indexOf('/');
        if (suffix < 0 || start < 0 || start >= suffix) return occurrence;
        String actor = occurrence.substring(start + 1, suffix);
        int separator = actor.lastIndexOf('|');
        return separator >= 0 ? actor.substring(separator + 1) : actor;
    }

    static boolean replyFanout(JsonArray faults) {
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
