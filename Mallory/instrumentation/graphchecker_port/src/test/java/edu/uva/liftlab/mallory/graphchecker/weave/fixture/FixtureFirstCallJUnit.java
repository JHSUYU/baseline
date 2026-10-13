package edu.uva.liftlab.mallory.graphchecker.weave.fixture;

import static org.junit.Assert.assertEquals;
import org.junit.Test;

public final class FixtureFirstCallJUnit {
    @Test public void originalFirstCall() {
        assertEquals(7, new FixtureFirstCall().callFirst());
    }
}
