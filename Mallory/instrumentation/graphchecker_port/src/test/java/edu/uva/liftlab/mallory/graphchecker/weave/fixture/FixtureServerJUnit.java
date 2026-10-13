package edu.uva.liftlab.mallory.graphchecker.weave.fixture;

import static org.junit.Assert.assertTrue;
import edu.uva.liftlab.mallory.graphchecker.runtime.MessageDoors;
import org.junit.Test;

public final class FixtureServerJUnit {
    @Test public void originalServerTest() {
        FixtureServer server = new FixtureServer();
        MessageDoors.registerNode(server, "HDFS", "NAMENODE", "nn-1");
        assertTrue(server.isReady(true));
    }
}
