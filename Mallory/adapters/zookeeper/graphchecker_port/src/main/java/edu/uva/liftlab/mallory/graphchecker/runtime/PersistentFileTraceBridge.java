package edu.uva.liftlab.mallory.graphchecker.runtime;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.BasicFileAttributes;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.concurrent.TimeUnit;

/**
 * Successful ZooKeeper file operations as exact stored-version handoffs.
 *
 * <p>The source weave calls these methods only after normal return. A failed
 * atomic write never publishes a version. The version includes the canonical
 * absolute path, complete bounded content digest, size, modification time,
 * and filesystem file key; another peer's acceptedEpoch file cannot match by
 * basename alone. This adapter is for one JVM MiniCluster, where
 * {@link MessageDoors} shares the version table among its peers.</p>
 */
public final class PersistentFileTraceBridge {
    private static final String TRANSPORT = "ZOOKEEPER_PERSISTED_FILE_V1";
    private static final long MAX_BYTES = 1024L * 1024L;

    private PersistentFileTraceBridge() {
    }

    /** The original test's successful FileUtils.write(File, ...). */
    public static void successfulWrite(Object file) {
        if (file instanceof File) {
            publish("WRITE", (File) file, null, null);
        } else {
            gap("FileUtils.write has no File argument");
        }
    }

    /** QuorumPeer.writeLongToFile returned after its atomic rename. */
    public static void zooKeeperEpochWrite(Object peer, Object name,
                                            long writtenValue) {
        publish("WRITE", epochFile(peer, name), peer, writtenValue);
    }

    /** QuorumPeer.readLongFromFile returned the exact parsed value. */
    public static void zooKeeperEpochRead(Object peer, Object name,
                                           long readValue) {
        publish("READ", epochFile(peer, name), peer, readValue);
    }

    private static File epochFile(Object peer, Object name) {
        if (!(name instanceof String) || peer == null) {
            gap("ZooKeeper epoch file has no peer or name");
            return null;
        }
        try {
            Method getFactory = peer.getClass().getMethod("getTxnFactory");
            Object factory = getFactory.invoke(peer);
            Method getSnapDir = factory.getClass().getMethod("getSnapDir");
            Object directory = getSnapDir.invoke(factory);
            if (directory instanceof File) {
                return new File((File) directory, (String) name);
            }
        } catch (ReflectiveOperationException | RuntimeException failure) {
            gap("ZooKeeper epoch path unavailable: " + failure);
            return null;
        }
        gap("ZooKeeper epoch snapshot directory is not a File");
        return null;
    }

    private static void publish(String operation, File file, Object owner,
                                Long observedValue) {
        if (file == null) return;
        try {
            Path path = file.toPath().toRealPath();
            BasicFileAttributes before = Files.readAttributes(path,
                    BasicFileAttributes.class);
            if (!before.isRegularFile() || before.size() > MAX_BYTES
                    || before.fileKey() == null) {
                gap("file has no bounded regular version identity: " + path);
                return;
            }
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] content = new byte[(int) before.size()];
            int count = 0;
            try (InputStream input = Files.newInputStream(path)) {
                while (count < content.length) {
                    int read = input.read(content, count, content.length - count);
                    if (read < 0) break;
                    count += read;
                }
                if (input.read() != -1) {
                    gap("file grew while fingerprinting: " + path);
                    return;
                }
            }
            BasicFileAttributes after = Files.readAttributes(path,
                    BasicFileAttributes.class);
            if (count != content.length || !after.isRegularFile()
                    || before.size() != after.size()
                    || !before.lastModifiedTime().equals(after.lastModifiedTime())
                    || !before.fileKey().equals(after.fileKey())) {
                gap("file changed while fingerprinting: " + path);
                return;
            }
            if (observedValue != null
                    && !matchesEpochValue(operation, content, observedValue)) {
                gap("epoch value differs from post-operation file: " + path);
                return;
            }
            byte[] hash = digest.digest(content);
            StringBuilder key = new StringBuilder(path.toString());
            key.append('|').append(before.size());
            key.append('|').append(before.lastModifiedTime().to(
                    TimeUnit.NANOSECONDS));
            key.append('|').append(before.fileKey()).append('|');
            for (byte value : hash) {
                key.append(Character.forDigit((value >>> 4) & 15, 16));
                key.append(Character.forDigit(value & 15, 16));
            }
            if ("WRITE".equals(operation)) {
                MessageDoors.stored(TRANSPORT, key.toString(), owner);
            } else {
                MessageDoors.fetched(TRANSPORT, key.toString(), owner);
            }
        } catch (IOException | NoSuchAlgorithmException | RuntimeException failure) {
            gap("file version unavailable for " + file + ": " + failure);
        }
    }

    private static boolean matchesEpochValue(String operation, byte[] bytes,
                                             long value) {
        String content = new String(bytes, StandardCharsets.UTF_8);
        if ("WRITE".equals(operation)) {
            return Long.toString(value).equals(content);
        }
        int newline = content.indexOf('\n');
        String firstLine = newline < 0 ? content : content.substring(0, newline);
        try {
            return Long.parseLong(firstLine) == value;
        } catch (NumberFormatException invalid) {
            return false;
        }
    }

    private static void gap(String detail) {
        MessageDoors.gap("PERSISTED_FILE_VERSION_GAP", TRANSPORT, detail);
    }
}
