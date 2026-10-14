package edu.uva.liftlab.mallory.graphchecker.weave.fixture;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.fail;
import org.junit.Test;

public final class FixtureCallThrowJUnit {
    @Test public void originalFactoryThrow() {
        assertEquals(1, FixtureCallThrow.factory(true));
        try {
            FixtureCallThrow.factory(false);
            fail("factory throw should propagate");
        } catch (IllegalStateException expected) {
            assertEquals("factory failure", expected.getMessage());
        }
    }
}
