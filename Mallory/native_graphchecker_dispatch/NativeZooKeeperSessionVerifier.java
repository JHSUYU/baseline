package edu.uva.liftlab.graphchecker.runtime;

import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;
import edu.uva.liftlab.graphchecker.contract.ScheduleEvent;
import edu.uva.liftlab.graphchecker.contract.SessionDir;
import edu.uva.liftlab.graphchecker.contract.SessionReader;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Stream;

/** Verifies one original GraphChecker SEED session and its typed wire pairs. */
public final class NativeZooKeeperSessionVerifier {
    private NativeZooKeeperSessionVerifier() { }

    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            throw new IllegalArgumentException("expected SESSION_DIR OUTPUT_JSON");
        }
        Path session = Paths.get(args[0]).toRealPath();
        Path output = Paths.get(args[1]).toAbsolutePath();
        String engine = System.getProperty("causynth.engine.jar", "");
        String sites = System.getProperty("causynth.typed.wire.sites", "auto");
        if (engine.isEmpty()) throw new IllegalArgumentException("engine is required");
        SessionDir directory = SessionDir.of(session.getParent().getParent(),
                session.getFileName().toString());
        SessionReader reader = SessionReader.read(directory);
        List<ScheduleEvent> schedule = reader.schedule();
        Set<String> selected = new HashSet<String>();
        if (sites.equals("auto")) {
            for (ScheduleEvent event : schedule) {
                if ((event.kind() == ScheduleEvent.Kind.SEND ||
                        event.kind() == ScheduleEvent.Kind.RECV) &&
                        event.site().startsWith("ZOOKEEPER_")) {
                    selected.add(event.site());
                }
            }
            List<String> ordered = new ArrayList<String>(selected);
            Collections.sort(ordered);
            sites = String.join(",", ordered);
        } else {
            for (String site : sites.split(",", -1)) {
                if (site.isEmpty() || !site.equals(site.trim()) ||
                        !selected.add(site)) {
                    throw new IllegalArgumentException("duplicate or empty wire site");
                }
            }
        }
        Map<String, String> sent = new HashMap<String, String>();
        Map<String, String> received = new HashMap<String, String>();
        int gaps = 0;
        for (ScheduleEvent event : schedule) {
            if (!selected.contains(event.site())) continue;
            if (event.kind() == ScheduleEvent.Kind.SEND) {
                String endpoint = event.endpoint();
                if (endpoint.isEmpty() || sent.put(endpoint, event.site()) != null) gaps++;
            } else if (event.kind() == ScheduleEvent.Kind.RECV) {
                String endpoint = event.received();
                if (endpoint.isEmpty() ||
                        received.put(endpoint, event.site()) != null) gaps++;
            }
        }
        int pairs = 0;
        for (Map.Entry<String, String> send : sent.entrySet()) {
            if (send.getValue().equals(received.get(send.getKey()))) pairs++;
            else gaps++;
        }
        for (Map.Entry<String, String> recv : received.entrySet()) {
            if (!recv.getValue().equals(sent.get(recv.getKey()))) gaps++;
        }
        JsonObject proof = new JsonObject();
        proof.addProperty("mode", "original_session_reader_complete");
        proof.addProperty("session_reader_incomplete", reader.incomplete());
        proof.addProperty("session_role", reader.seed() ? "SEED" : "OTHER");
        proof.addProperty("session_id", reader.sessionId());
        proof.addProperty("session_dir_path", session.toString());
        proof.addProperty("session_tree_sha256", treeDigest(session));
        proof.addProperty("session_manifest_sha256", digest(session.resolve("manifest.json")));
        proof.addProperty("engine_jar_sha256", digest(Paths.get(engine).toRealPath()));
        proof.addProperty("schedule_wire_sites", sites);
        proof.addProperty("schedule_wire_pairs", pairs);
        proof.addProperty("schedule_pairing_gaps", gaps);
        proof.addProperty("gap_rows", reader.gaps().size());
        Files.write(output, new GsonBuilder().setPrettyPrinting().create()
                .toJson(proof).getBytes(StandardCharsets.UTF_8));
    }

    private static String treeDigest(Path directory) throws IOException {
        List<Path> files = new ArrayList<Path>();
        try (Stream<Path> found = Files.walk(directory)) {
            found.filter(Files::isRegularFile).forEach(files::add);
        }
        files.sort((left, right) -> directory.relativize(left).toString().replace('\\', '/')
                .compareTo(directory.relativize(right).toString().replace('\\', '/')));
        MessageDigest hash = sha256();
        for (Path file : files) {
            hash.update(directory.relativize(file).toString().replace('\\', '/')
                    .getBytes(StandardCharsets.UTF_8));
            hash.update((byte) 0);
            hash.update(fromHex(digest(file)));
        }
        return hex(hash.digest());
    }

    private static String digest(Path file) throws IOException {
        MessageDigest hash = sha256();
        try (java.io.InputStream input = Files.newInputStream(file)) {
            byte[] block = new byte[1 << 20];
            for (int length; (length = input.read(block)) != -1; ) {
                hash.update(block, 0, length);
            }
        }
        return hex(hash.digest());
    }

    private static MessageDigest sha256() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    private static byte[] fromHex(String value) {
        byte[] raw = new byte[value.length() / 2];
        for (int i = 0; i < raw.length; i++) {
            raw[i] = (byte) Integer.parseInt(value.substring(2 * i, 2 * i + 2), 16);
        }
        return raw;
    }

    private static String hex(byte[] raw) {
        StringBuilder result = new StringBuilder(raw.length * 2);
        for (byte value : raw) result.append(String.format("%02x", value & 0xff));
        return result.toString();
    }
}
