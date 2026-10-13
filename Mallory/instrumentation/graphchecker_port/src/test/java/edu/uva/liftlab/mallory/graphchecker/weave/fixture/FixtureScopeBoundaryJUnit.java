package edu.uva.liftlab.mallory.graphchecker.weave.fixture;

import static org.junit.Assert.assertEquals;
import org.junit.Test;

public final class FixtureScopeBoundaryJUnit {
    @Test public void originalScopeBoundary() {
        assertEquals(5, new FixtureScopeBoundary().run());
    }
}
