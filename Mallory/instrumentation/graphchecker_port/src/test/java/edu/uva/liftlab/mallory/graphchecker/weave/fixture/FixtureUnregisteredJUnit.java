package edu.uva.liftlab.mallory.graphchecker.weave.fixture;

import static org.junit.Assert.assertTrue;
import org.junit.Test;

public final class FixtureUnregisteredJUnit {
    @Test public void missingSourceBinding() {
        assertTrue(new FixtureServer().isReady(true));
    }
}
