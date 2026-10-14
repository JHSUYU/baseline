package edu.uva.liftlab.mallory.graphchecker.runtime;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import edu.uva.liftlab.mallory.graphchecker.contract.CausalContext;
import edu.uva.liftlab.mallory.graphchecker.contract.OccurrenceAddress;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Bounded, argument-free evidence for distinguishing expected target throws. */
final class TargetThrowFingerprint {
    private static final int MESSAGE_PREFIX = 512;
    private static final int MAX_NUMERIC_ATTRIBUTES = 6;
    private static final int MAX_STACK_METHODS = 16;
    private static final Pattern LABELED_NUMBER = Pattern.compile(
            "(?:^|[^A-Za-z0-9_])([A-Za-z][A-Za-z0-9_]{0,31}" +
            "(?:[ ]+[A-Za-z][A-Za-z0-9_]{0,31})?)\\s*[:=]\\s*(-?[0-9]{1,19})");

    private TargetThrowFingerprint() { }

    static JsonObject fields(String siteId, OccurrenceAddress occurrence,
                             Object owner, Throwable thrown) {
        JsonObject result = new JsonObject();
        result.addProperty("fingerprintVersion", 1);
        String exceptionClass = thrown == null ? "" : thrown.getClass().getName();
        String role = sourceRole(owner);
        String contextForm = occurrence == null ? "UNATTRIBUTED"
                : occurrence.context().form().name();
        String contextRole = "";
        String contextApi = "";
        if (occurrence != null && occurrence.context().form() == CausalContext.Form.ROOT) {
            CausalContext.Root root = (CausalContext.Root) occurrence.context();
            contextRole = root.role().name();
            contextApi = root.api();
        } else if (occurrence != null &&
                occurrence.context().form() == CausalContext.Form.LOST) {
            contextRole = ((CausalContext.Lost) occurrence.context()).role().name();
        }
        result.addProperty("sourceRole", role);
        result.addProperty("causalForm", contextForm);
        result.addProperty("causalRole", contextRole);
        // An API label may contain a user path. Record only a bounded digest,
        // and omit it from the structural key because dynamic paths vary.
        result.addProperty("causalApiPrefixSha256", sha256(contextApi.substring(
                0, Math.min(contextApi.length(), 128))));
        result.addProperty("causalApiLength", contextApi.length());

        JsonArray stackMethods = stackMethods();
        result.add("stackMethods", stackMethods);
        // Stable across nodes, occurrence numbers and key rotation. Numeric
        // values remain separate evidence, never part of the profile key.
        result.addProperty("structuralFingerprint", sha256(
                siteId + "\n" + exceptionClass + "\n" + role + "\n"
                + contextForm + "\n" + contextRole
                + "\n" + stackMethods.toString()));

        String message = thrown == null ? null : thrown.getMessage();
        if (message != null) {
            String prefix = message.substring(0, Math.min(message.length(), MESSAGE_PREFIX));
            result.addProperty("messageLength", message.length());
            result.addProperty("messagePrefixSha256", sha256(prefix));
            result.addProperty("messageTruncated", message.length() > MESSAGE_PREFIX);
            JsonObject numeric = new JsonObject();
            Matcher matcher = LABELED_NUMBER.matcher(prefix);
            int seen = 0;
            while (matcher.find() && seen < MAX_NUMERIC_ATTRIBUTES) {
                String label = matcher.group(1).trim().replace(' ', '_')
                        .toLowerCase(Locale.ROOT);
                if (!numeric.has(label)) {
                    numeric.addProperty(label, matcher.group(2));
                    seen++;
                }
            }
            result.add("numericAttributes", numeric);
        }
        return result;
    }

    private static String sourceRole(Object owner) {
        SourceRef source = owner == null ? TraceRows.snapshot().source
                : TraceRows.source(owner);
        return source == null ? "" : source.role();
    }

    private static JsonArray stackMethods() {
        JsonArray result = new JsonArray();
        for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
            String clazz = frame.getClassName();
            if (clazz.equals(Thread.class.getName()) ||
                    clazz.equals(TargetThrowFingerprint.class.getName()) ||
                    clazz.equals(MessageDoors.class.getName())) continue;
            // No source path, line, arguments, local variables, or messages.
            result.add(clazz + "#" + frame.getMethodName());
            if (result.size() == MAX_STACK_METHODS) break;
        }
        return result;
    }

    private static String sha256(String value) {
        try {
            byte[] bytes = MessageDigest.getInstance("SHA-256").digest(
                    value.getBytes(StandardCharsets.UTF_8));
            StringBuilder result = new StringBuilder(bytes.length * 2);
            for (byte b : bytes) result.append(String.format("%02x", b & 0xff));
            return result.toString();
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 unavailable", impossible);
        }
    }
}
