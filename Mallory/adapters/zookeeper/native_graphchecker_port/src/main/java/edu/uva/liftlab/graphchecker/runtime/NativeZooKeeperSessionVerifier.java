package edu.uva.liftlab.graphchecker.runtime;

import com.google.gson.JsonObject;
import edu.uva.liftlab.graphchecker.contract.ScheduleEvent;
import edu.uva.liftlab.graphchecker.contract.RowCodec;
import edu.uva.liftlab.graphchecker.contract.SessionDir;
import edu.uva.liftlab.graphchecker.contract.SessionReader;
import java.io.BufferedReader;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.stream.Stream;

/** Read the complete original GraphChecker session, then attest its files. */
public final class NativeZooKeeperSessionVerifier {
    private NativeZooKeeperSessionVerifier() { }

    public static void main(String[] args) throws Exception {
        if (args.length != 2) throw new IllegalArgumentException(
                "usage: -Dcausynth.engine.jar=<pin> "
                        + "NativeZooKeeperSessionVerifier <session-dir> <receipt-path>");
        Path directory = Paths.get(args[0]).toRealPath();
        Path receiptFile = Paths.get(args[1]).toAbsolutePath().normalize();
        if (receiptFile.startsWith(directory)) throw new IllegalArgumentException(
                "receipt must be outside the attested session tree");
        String engineArgument = System.getProperty("causynth.engine.jar", "");
        if (engineArgument.isEmpty()) throw new IllegalArgumentException(
                "source-built engine jar pin is required");
        Path engine = Paths.get(engineArgument).toRealPath();
        if (!"sessions".equals(directory.getParent().getFileName().toString())) {
            throw new IllegalArgumentException("expected iteration/sessions/<session-id>");
        }
        Path iteration = directory.getParent().getParent();
        SessionReader session = SessionReader.read(SessionDir.of(iteration,
                directory.getFileName().toString()));
        String configuredSites = System.getProperty("causynth.typed.wire.sites", "");
        Set<String> wireSites = new HashSet<String>();
        for (String name : configuredSites.split(",")) {
            if (!name.trim().isEmpty()) wireSites.add(name.trim());
        }
        if (wireSites.isEmpty()) throw new IllegalArgumentException(
                "-Dcausynth.typed.wire.sites needs at least one exact site");
        Map<String, ScheduleEvent> sent = new HashMap<String, ScheduleEvent>();
        int pairs = 0;
        int pairingGaps = 0;
        List<ScheduleEvent> schedule = session.schedule();
        int completeScheduleEvents = strictScheduleEvents(
                directory.resolve("schedule.jsonl"));
        if (schedule.size() != completeScheduleEvents) {
            throw new IllegalStateException("original SessionReader truncated the schedule");
        }
        for (ScheduleEvent event : schedule) {
            if (!wireSites.contains(event.site())) continue;
            if (event.kind() == ScheduleEvent.Kind.SEND) {
                if (event.endpoint().isEmpty()
                        || sent.put(event.endpoint(), event) != null) pairingGaps++;
            } else if (event.kind() == ScheduleEvent.Kind.RECV) {
                ScheduleEvent producer = sent.remove(event.received());
                if (producer == null || producer.seq() >= event.seq()
                        || !producer.site().equals(event.site())) pairingGaps++;
                else pairs++;
            }
        }
        pairingGaps += sent.size();
        JsonObject receipt = new JsonObject();
        receipt.addProperty("mode", "original_session_reader_complete");
        receipt.addProperty("session_reader_incomplete", session.incomplete());
        receipt.addProperty("session_dir_path", directory.toString());
        receipt.addProperty("session_tree_sha256", treeHash(directory));
        receipt.addProperty("session_manifest_sha256", hash(directory.resolve("manifest.json")));
        receipt.addProperty("engine_jar_sha256", hash(engine));
        receipt.addProperty("session_id", session.sessionId());
        receipt.addProperty("session_role", session.seed() ? "SEED" : "OTHER");
        receipt.addProperty("schedule_events", completeScheduleEvents);
        receipt.addProperty("schedule_wire_sites", configuredSites);
        receipt.addProperty("schedule_wire_pairs", pairs);
        receipt.addProperty("schedule_pairing_gaps", pairingGaps);
        receipt.addProperty("gap_rows", session.gaps().size());
        receipt.addProperty("target_rows", session.targets().size());
        receipt.addProperty("export_rows", session.exports().size());
        receipt.addProperty("attach_rows", session.attaches().size());
        Path parent = receiptFile.getParent();
        Files.createDirectories(parent);
        Path temporary = Files.createTempFile(parent, "session-reader-", ".json.tmp");
        Files.write(temporary, (receipt.toString() + "\n")
                .getBytes(StandardCharsets.UTF_8));
        Files.move(temporary, receiptFile, StandardCopyOption.ATOMIC_MOVE,
                StandardCopyOption.REPLACE_EXISTING);
        System.out.println(receipt.toString());
        if (!session.incomplete().isEmpty()) System.exit(2);
    }

    /** SessionReader permits a readable prefix; a gate requires every line. */
    private static int strictScheduleEvents(Path file) throws Exception {
        int events = 0;
        long lastSequence = -1L;
        try (BufferedReader lines = Files.newBufferedReader(file,
                StandardCharsets.UTF_8)) {
            for (String line; (line = lines.readLine()) != null;) {
                JsonObject row = RowCodec.fromLine(line);
                if (row.has("mark")) {
                    if (!row.has("at") || !row.get("mark").isJsonPrimitive()) {
                        throw new IllegalStateException("invalid schedule mark");
                    }
                    row.get("at").getAsLong();
                    continue;
                }
                ScheduleEvent event = RowCodec.readScheduleEvent(row);
                if (event.seq() != lastSequence + 1L) {
                    throw new IllegalStateException("schedule event sequence has a hole");
                }
                lastSequence = event.seq();
                events++;
            }
        }
        return events;
    }

    private static String treeHash(Path directory) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        List<Path> files = new ArrayList<Path>();
        try (Stream<Path> walk = Files.walk(directory)) {
            walk.filter(Files::isRegularFile).forEach(files::add);
        }
        if (files.isEmpty()) throw new IllegalArgumentException("empty session tree");
        Collections.sort(files);
        for (Path file : files) {
            digest.update(directory.relativize(file).toString()
                    .getBytes(StandardCharsets.UTF_8));
            digest.update((byte) 0);
            digest.update(fileDigest(file));
        }
        return hex(digest.digest());
    }

    private static String hash(Path file) throws Exception {
        return hex(fileDigest(file));
    }

    private static byte[] fileDigest(Path file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream in = Files.newInputStream(file)) {
            byte[] buffer = new byte[8192];
            for (int n; (n = in.read(buffer)) != -1;) {
                digest.update(buffer, 0, n);
            }
        }
        return digest.digest();
    }

    private static String hex(byte[] bytes) {
        StringBuilder value = new StringBuilder(bytes.length * 2);
        for (byte one : bytes) {
            value.append(Character.forDigit((one >>> 4) & 15, 16));
            value.append(Character.forDigit(one & 15, 16));
        }
        return value.toString();
    }
}
