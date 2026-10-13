package edu.uva.liftlab.mallory.graphchecker.weave.fixture;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.fail;
import org.junit.Test;

public final class FixtureJUnit {
    @Test public void originalTestMethod() {
        FixtureOperation operation = new FixtureOperation();
        assertEquals(0, operation.classify(0));
        try {
            operation.classify(1);
            fail("expected original exception");
        } catch (IllegalStateException expected) {
            assertEquals("positive", expected.getMessage());
        }
        assertEquals(11, operation.choose(1));
        assertEquals(22, operation.choose(2));
    }
}
