package edu.uva.liftlab.mallory.nativerows;

import com.google.gson.JsonObject;
import edu.uva.liftlab.graphchecker.contract.ActivationRow;
import edu.uva.liftlab.graphchecker.contract.AttachRow;
import edu.uva.liftlab.graphchecker.contract.Endpoint;
import edu.uva.liftlab.graphchecker.contract.ExportRow;
import edu.uva.liftlab.graphchecker.contract.GapClass;
import edu.uva.liftlab.graphchecker.contract.GapKind;
import edu.uva.liftlab.graphchecker.contract.LocationId;
import edu.uva.liftlab.graphchecker.contract.OccurrenceAddress;
import edu.uva.liftlab.graphchecker.contract.ReadRow;
import edu.uva.liftlab.graphchecker.runtime.RowRuntime;
import edu.uva.liftlab.graphchecker.runtime.SessionPublisher;
import java.io.IOException;
import java.net.URISyntaxException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/**
 * Opt-in bridge into the original GraphChecker row recorder. The caller must
 * provide native occurrence and endpoint addresses and observed VM versions;
 * this bridge never reconstructs them from a post-hoc Mallory trace.
 */
public final class NativeRowHooks {
    private static final String THIN_SHA =
            "8897901dee05750e9aa456978091190337aa3762a813527fbd510ff8d3c38880";
    private static final String FAT_SHA =
            "222f2d74236d432c6ad4001f5d9423b5bd9567084ad668089676ccf8de43e343";

    private final SessionPublisher session;

    private NativeRowHooks(SessionPublisher session) {
        this.session = session;
    }

    /** resultFile must be below an iteration-* directory, as in GraphChecker. */
    public static NativeRowHooks open(Path resultFile) throws IOException {
        verifyRuntimeJar();
        if (resultFile == null) throw new IllegalArgumentException("resultFile");
        Path iteration = resultFile.toAbsolutePath().getParent();
        while (iteration != null && (iteration.getFileName() == null
                || !iteration.getFileName().toString().startsWith("iteration-"))) {
            iteration = iteration.getParent();
        }
        if (iteration == null) {
            throw new IllegalArgumentException("resultFile is outside an iteration-* directory");
        }
        RowRuntime.configure(resultFile);
        if (!RowRuntime.open()) throw new IllegalStateException("GraphChecker RowRuntime did not open");
        return new NativeRowHooks(SessionPublisher.of(iteration, RowRuntime.sessionId()));
    }

    public String sessionId() {
        return RowRuntime.sessionId();
    }

    public void activation(String renderedAddress, String taskId,
                           String threadKey, boolean focused,
                           boolean instrumented, Endpoint producer) {
        OccurrenceAddress occurrence = OccurrenceAddress.parse(renderedAddress);
        session.activation(ActivationRow.of(sessionId(), occurrence,
                taskId == null ? "" : taskId, focused, instrumented,
                threadKey == null ? "" : threadKey, producer));
    }

    /** condition must be the captured expression DAG, not a boolean label. */
    public void decision(String address, long vmSeq, String site, int ordinal,
                         boolean outcome, JsonObject condition) {
        requireExpression(condition, "decision");
        RowRuntime.decision(OccurrenceAddress.parse(address), vmSeq, site,
                ordinal, outcome, condition);
    }

    /** version must come from the runtime store-version hook for this location. */
    public void write(String address, long vmSeq, String site,
                      LocationId location, long version,
                      JsonObject storedExpression, String javaType,
                      String siteIndex) {
        requireExpression(storedExpression, "write");
        requireState(location, version, siteIndex);
        RowRuntime.write(OccurrenceAddress.parse(address), vmSeq, site,
                location, version, storedExpression, javaType, siteIndex,
                null, null, false);
    }

    /** observedVersion is the version seen by this exact load, never the latest. */
    public void read(String address, long vmSeq, String site,
                     LocationId location, long observedVersion,
                     String symbol, String javaType, String concreteValue,
                     String siteIndex) {
        requireState(location, observedVersion, siteIndex);
        if (symbol == null || symbol.isEmpty()) {
            throw new IllegalArgumentException("read requires a captured value symbol");
        }
        RowRuntime.read(OccurrenceAddress.parse(address), vmSeq, site,
                location, observedVersion, symbol, javaType, concreteValue,
                siteIndex, ReadRow.UNKNOWN_VERSION);
    }

    /** fatalArm refers to the supplied predicate, observedFatal to the run. */
    public void target(String address, long vmSeq, String anchorSite,
                       JsonObject condition, boolean fatalArm,
                       boolean observedFatal) {
        requireExpression(condition, "target");
        RowRuntime.target(OccurrenceAddress.parse(address), vmSeq,
                anchorSite, condition, fatalArm, observedFatal, true);
    }

    /**
     * Publish a payload captured at an exact sender endpoint. This method
     * requires the original payload expression and its wire handle.
     */
    public void export(Endpoint endpoint, long vmSeq,
                       JsonObject payload, String javaType, long handle,
                       String recordedValue) {
        requireExpression(payload, "export");
        if (endpoint == null) throw new IllegalArgumentException("export endpoint");
        String ref = RowRuntime.expressionRef(payload);
        session.export(ExportRow.of(sessionId(), vmSeq, endpoint, ref,
                javaType, handle, recordedValue));
    }

    /** Producer is the exact endpoint carried by the message, not a guess. */
    public void attach(Endpoint consumer, Endpoint producer,
                       long vmSeq, String symbol, String javaType,
                       String arrival, String correlationId,
                       String pairingKey) {
        if (consumer == null || producer == null) {
            throw new IllegalArgumentException("attach requires exact endpoints");
        }
        if (symbol == null || symbol.isEmpty()) {
            throw new IllegalArgumentException("attach requires a minted handoff symbol");
        }
        if (!AttachRow.HANDLE.equals(pairingKey)
                && !AttachRow.CORRELATION_PORT.equals(pairingKey)) {
            throw new IllegalArgumentException("attach requires an exact pairing key");
        }
        session.attach(AttachRow.of(sessionId(), vmSeq, consumer, symbol,
                javaType, arrival, false, null, producer, correlationId,
                pairingKey));
    }

    /** A missing exact version or expression is an explicit blocking gap. */
    public void missingEvidence(String subject, String detail) {
        if (subject == null || subject.isEmpty()) {
            throw new IllegalArgumentException("gap requires a subject");
        }
        RowRuntime.gap(GapKind.UNSTATED_VALUE, GapClass.BLOCKING, subject,
                detail == null ? "native hook could not capture this value" : detail);
    }

    private static void requireExpression(JsonObject value, String kind) {
        if (value == null || !value.has("_exp") || value.get("_exp").isJsonNull()) {
            throw new IllegalArgumentException(kind + " requires a captured VM expression");
        }
    }

    private static void requireState(LocationId location, long version,
                                     String siteIndex) {
        if (location == null || version < 0L || siteIndex == null) {
            throw new IllegalArgumentException("state hook requires exact location, version, and index");
        }
    }

    private static void verifyRuntimeJar() throws IOException {
        Path jar;
        try {
            jar = java.nio.file.Paths.get(RowRuntime.class.getProtectionDomain()
                    .getCodeSource().getLocation().toURI());
        } catch (URISyntaxException bad) {
            throw new IOException("Cannot locate GraphChecker RowRuntime", bad);
        }
        if (!Files.isRegularFile(jar)) {
            throw new IOException("GraphChecker RowRuntime is not loaded from a pinned jar: " + jar);
        }
        String digest = sha256(jar);
        if (!THIN_SHA.equals(digest) && !FAT_SHA.equals(digest)) {
            throw new IOException("GraphChecker RowRuntime jar hash differs: " + digest);
        }
    }

    private static String sha256(Path file) throws IOException {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] bytes = Files.readAllBytes(file);
            digest.update(bytes);
            StringBuilder result = new StringBuilder();
            for (byte b : digest.digest()) result.append(String.format("%02x", b & 255));
            return result.toString();
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }
}
