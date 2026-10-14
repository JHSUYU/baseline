package edu.uva.liftlab.graphchecker.runtime;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertSame;

import edu.uva.liftlab.graphchecker.contract.OccurrenceAddress;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.Test;

/** A nested selected region must keep the physical actor that executes it. */
public final class ActorBoundaryOccurrenceTest {
    @Test public void nestedRegionOnAnotherActorOpensItsOwnOccurrence() {
        OccurrenceAddress client = Identity.occurrence(
                "native-junit#epoch0", "REGION.client", true);
        try {
            OccurrenceAddress peer = Identity.occurrence(
                    "zk-peer-2#epoch0", "REGION.peer", true);
            try {
                assertEquals("zk-peer-2#epoch0", peer.node().render());
                assertNotEquals(client.id(), peer.id());
                assertSame(peer, Identity.currentOccurrence("zk-peer-2#epoch0"));
                OccurrenceAddress folded = Identity.occurrence(
                        "zk-peer-2#epoch0", "REGION.peer-nested", true);
                try {
                    assertSame(peer, folded);
                    assertSame(peer, Identity.currentOccurrence("zk-peer-2#epoch0"));
                } finally {
                    Identity.regionExit();
                }
            } finally {
                Identity.regionExit();
            }
            assertSame(client, Identity.currentOccurrence("native-junit#epoch0"));
        } finally {
            Identity.regionExit();
        }
    }

    @Test public void childThreadUsesItsRegisteredPeerActor() throws Exception {
        Identity.occurrence("native-junit#epoch0", "REGION.client", true);
        try {
            AtomicReference<OccurrenceAddress> result = new AtomicReference<>();
            AtomicReference<Throwable> failure = new AtomicReference<>();
            Thread child = new Thread(() -> {
                try {
                    OccurrenceAddress peer = Identity.occurrence(
                            "zk-peer-1#epoch0", "REGION.peer", true);
                    try {
                        assertEquals("zk-peer-1#epoch0", peer.node().render());
                        assertSame(peer, Identity.currentOccurrence("zk-peer-1#epoch0"));
                        result.set(peer);
                    } finally {
                        Identity.regionExit();
                    }
                } catch (Throwable thrown) {
                    failure.set(thrown);
                }
            });
            child.start();
            child.join(5000);
            if (child.isAlive()) throw new AssertionError("child did not finish");
            if (failure.get() != null) throw new AssertionError(failure.get());
            assertEquals("zk-peer-1#epoch0", result.get().node().render());
        } finally {
            Identity.regionExit();
        }
    }
}
