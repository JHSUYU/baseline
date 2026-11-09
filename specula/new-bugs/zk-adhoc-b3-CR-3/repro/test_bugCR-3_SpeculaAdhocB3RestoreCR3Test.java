/*
 * CR-3 reproduction, Level 0 (no failpoints, no internal calls, no source change).
 * Variant of TestAdhocWorkloadB3: same module, package, path and container prelude, same final getData.
 * Differences: the server is the real ZooKeeperServerMain with its own ContainerManager
 * (ZooKeeperServerMain.java:170), and an operator restores a backup through the documented
 * HTTP admin commands (zookeeperSnapshotAndRestore.md).
 * Nothing here touches ZKDatabase, DataTree or the manager.
 */

package org.apache.zookeeper.server;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.Collections;
import org.apache.zookeeper.CreateMode;
import org.apache.zookeeper.KeeperException;
import org.apache.zookeeper.PortAssignment;
import org.apache.zookeeper.ZKTestCase;
import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.ZooDefs.Ids;
import org.apache.zookeeper.ZooKeeper;
import org.apache.zookeeper.common.IOUtils;
import org.apache.zookeeper.data.ACL;
import org.apache.zookeeper.data.Id;
import org.apache.zookeeper.data.Stat;
import org.apache.zookeeper.server.auth.DigestAuthenticationProvider;
import org.apache.zookeeper.test.ClientBase;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

public class SpeculaAdhocB3RestoreCR3Test extends ZKTestCase {

    private static final String PATH = "/adhoc-workload-b3";
    private static final String NEVER_USED = "/cr3-never-used";
    private static final String CONTROL = "/cr3-control";
    private static final byte[] V1 = "v1".getBytes(StandardCharsets.UTF_8);
    private static final byte[] V2 = "v2".getBytes(StandardCharsets.UTF_8);
    private static final String AUTH = "digest root:root_passwd";

    /** -Dcr3.defaults=true keeps the shipped intervals: 60 s check, 5 min never-used. */
    private static final boolean DEFAULTS = Boolean.getBoolean("cr3.defaults");
    private static final int CHECK_MS = DEFAULTS ? 60000 : 4000;
    private static final long NEVER_USED_MS = DEFAULTS ? 300000 : 20000;
    private static final int RECREATE_CYCLES = DEFAULTS ? 1 : 3;

    private final int clientPort = PortAssignment.unique();
    private final int adminPort = PortAssignment.unique();
    private final String hostPort = "127.0.0.1:" + clientPort;
    private ZooKeeperServerMainTest.MainThread main;

    private static void say(String format, Object... args) {
        System.out.println("[CR3] " + System.currentTimeMillis() + " " + String.format(format, args));
    }

    @BeforeEach
    public void startServer() throws Exception {
        ClientBase.setupTestEnv();
        System.setProperty("zookeeper.4lw.commands.whitelist", "*");
        System.setProperty("zookeeper.admin.enableServer", "true");
        System.setProperty("zookeeper.admin.serverPort", String.valueOf(adminPort));
        if (!DEFAULTS) {
            // time compression through the manager's own documented keys
            System.setProperty("znode.container.checkIntervalMs", String.valueOf(CHECK_MS));
            System.setProperty("znode.container.maxNeverUsedIntervalMs", String.valueOf(NEVER_USED_MS));
        }
        main = new ZooKeeperServerMainTest.MainThread(clientPort, true, null);
        main.start();
        assertTrue(ClientBase.waitForServerUp(hostPort, ClientBase.CONNECTION_TIMEOUT), "server up");
        say("server up: ZooKeeperServerMain client=%d admin=%d checkMs=%d neverUsedMs=%d defaults=%s",
            clientPort, adminPort, CHECK_MS, NEVER_USED_MS, DEFAULTS);
    }

    @AfterEach
    public void stopServer() throws Exception {
        main.shutdown();
        main.join(30000);
        main.deleteDirs();
        System.clearProperty("zookeeper.admin.enableServer");
        System.clearProperty("zookeeper.admin.serverPort");
        System.clearProperty("znode.container.checkIntervalMs");
        System.clearProperty("znode.container.maxNeverUsedIntervalMs");
    }

    private ZooKeeper client() throws Exception {
        ZooKeeper zk = ClientBase.createZKClient(hostPort);
        zk.addAuthInfo("digest", "root:root_passwd".getBytes(StandardCharsets.UTF_8));
        return zk;
    }

    private static String kind(Stat s) {
        return s == null ? "absent" : "ephemeralOwner=0x" + Long.toHexString(s.getEphemeralOwner()) + " cversion=" + s.getCversion();
    }

    /** curl -H 'Authorization: ...' http://host:adminPort/commands/snapshot?streaming=true --output file */
    private File httpSnapshot() throws Exception {
        URL url = new URL("http://127.0.0.1:" + adminPort + "/commands/snapshot?streaming=true");
        HttpURLConnection c = (HttpURLConnection) url.openConnection();
        c.setRequestProperty("Authorization", AUTH);
        assertEquals(200, c.getResponseCode(), "snapshot status");
        File f = File.createTempFile("cr3-backup", ".snap");
        try (InputStream in = c.getInputStream()) {
            Files.copy(in, f.toPath(), StandardCopyOption.REPLACE_EXISTING);
        }
        say("GET /commands/snapshot -> 200 last_zxid=%s bytes=%d", c.getHeaderField("last_zxid"), f.length());
        return f;
    }

    /** curl -H 'Content-Type:application/octet-stream' -H 'Authorization: ...' -POST .../commands/restore --data-binary @file */
    private void httpRestore(File f) throws Exception {
        URL url = new URL("http://127.0.0.1:" + adminPort + "/commands/restore");
        HttpURLConnection c = (HttpURLConnection) url.openConnection();
        c.setRequestMethod("POST");
        c.setDoOutput(true);
        c.setRequestProperty("Content-Type", "application/octet-stream");
        c.setRequestProperty("Authorization", AUTH);
        try (OutputStream out = c.getOutputStream()) {
            Files.copy(f.toPath(), out);
        }
        assertEquals(200, c.getResponseCode(), "restore status");
        ByteArrayOutputStream body = new ByteArrayOutputStream();
        try (InputStream in = c.getInputStream()) {
            IOUtils.copyBytes(in, body, 1024, false);
        }
        say("POST /commands/restore -> 200 %s", new String(body.toByteArray(), StandardCharsets.UTF_8).replaceAll("\\s+", " "));
    }

    /** Reads until the server answers NONODE; returns the wait in ms. */
    private long readUntilNoNode(ZooKeeper zk, String path, long timeoutMs) throws Exception {
        long start = System.currentTimeMillis();
        while (System.currentTimeMillis() - start < timeoutMs) {
            try {
                zk.getData(path, false, null);
            } catch (KeeperException.NoNodeException gone) {
                long waited = System.currentTimeMillis() - start;
                say("getData(%s) -> %s after %d ms", path, gone, waited);
                return waited;
            }
            Thread.sleep(100);
        }
        return fail("no NoNodeException for " + path + " within " + timeoutMs + " ms");
    }

    @Test
    public void restoreLeavesManagerOnOldTree() throws Exception {
        ZooKeeper zk = client();
        zk.setACL("/", Collections.singletonList(new ACL(ZooDefs.Perms.ALL,
            new Id("digest", DigestAuthenticationProvider.generateDigest("root:root_passwd")))), -1);

        // the state the operator backs up: ordinary persistent nodes
        zk.create(PATH, V1, Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
        zk.create(NEVER_USED, V1, Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
        zk.create(CONTROL, V1, Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
        File backup = httpSnapshot();

        // later application activity: the two paths become containers (old tree only)
        zk.delete(NEVER_USED, -1);
        zk.create(NEVER_USED, new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.CONTAINER);
        zk.delete(PATH, -1);
        // TestAdhocWorkloadB3's prelude: a container loses its last child
        zk.create(PATH, new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.CONTAINER);
        zk.create(PATH + "/child", new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
        zk.delete(PATH + "/child", -1);
        say("old tree before restore: %s {%s}  %s {%s}", PATH, kind(zk.exists(PATH, false)), NEVER_USED, kind(zk.exists(NEVER_USED, false)));

        // documented procedure: block client traffic, restore, unblock
        zk.close();
        httpRestore(backup);
        long restoredAt = System.currentTimeMillis();
        ZooKeeper zk2 = client();

        // never-used container is not a candidate yet, so these reads are not racing a check
        assertArrayEquals(V1, zk2.getData(NEVER_USED, false, null));
        assertArrayEquals(V1, zk2.getData(CONTROL, false, null));
        say("restored tree: %s {%s} data=v1  %s {%s}  %s {%s} data=v1",
            PATH, kind(zk2.exists(PATH, false)), NEVER_USED, kind(zk2.exists(NEVER_USED, false)), CONTROL, kind(zk2.exists(CONTROL, false)));

        if (Boolean.getBoolean("cr3.expectSurvive")) {
            // fix control only (test_bugCR-3_fix_control.patch): a manager on the live tree must not touch these
            Thread.sleep(NEVER_USED_MS + 3L * CHECK_MS);
            assertArrayEquals(V1, zk2.getData(PATH, false, null));
            assertArrayEquals(V1, zk2.getData(NEVER_USED, false, null));
            assertArrayEquals(V1, zk2.getData(CONTROL, false, null));
            say("RESULT fix control: all restored nodes survived %d ms after restore", System.currentTimeMillis() - restoredAt);
            zk2.close();
            return;
        }

        // consequence 1: restored PERSISTENT node at the old used-container's path
        readUntilNoNode(zk2, PATH, 3L * CHECK_MS + 15000);
        // consequence 2: restored PERSISTENT node at the old never-used container's path
        readUntilNoNode(zk2, NEVER_USED, NEVER_USED_MS + 3L * CHECK_MS + 15000);
        say("restored nodes gone %d ms after restore", System.currentTimeMillis() - restoredAt);

        // permanence: the frozen tree keeps nominating the path, so the workload's own recovery loses too
        for (int cycle = 1; cycle <= RECREATE_CYCLES; cycle++) {
            zk2.create(PATH, V2, Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
            assertArrayEquals(V2, zk2.getData(PATH, false, null));
            say("re-created persistent %s (cycle %d) {%s}", PATH, cycle, kind(zk2.exists(PATH, false)));
            readUntilNoNode(zk2, PATH, 3L * CHECK_MS + 15000);
        }

        // control: a restored node the old tree did not nominate survives all of those checks
        assertArrayEquals(V1, zk2.getData(CONTROL, false, null));
        say("control %s still present with data=v1 after %d ms", CONTROL, System.currentTimeMillis() - restoredAt);
        zk2.close();
        Files.delete(backup.toPath());
        say("RESULT restoreLeavesManagerOnOldTree: BUG TRIGGERED");
    }

    /** Same order without the restore: a manager on the live tree leaves the persistent node alone. */
    @Test
    public void controlNoRestore() throws Exception {
        ZooKeeper zk = client();
        zk.create(PATH, new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.CONTAINER);
        zk.create(PATH + "/child", new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
        zk.delete(PATH + "/child", -1);
        readUntilNoNode(zk, PATH, 3L * CHECK_MS + 15000);
        zk.create(PATH, V2, Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
        Thread.sleep(4L * CHECK_MS);
        assertNotNull(zk.exists(PATH, false));
        assertArrayEquals(V2, zk.getData(PATH, false, null));
        say("RESULT controlNoRestore: persistent %s survived %d ms of checks {%s}", PATH, 4L * CHECK_MS, kind(zk.exists(PATH, false)));
        zk.close();
    }
}
