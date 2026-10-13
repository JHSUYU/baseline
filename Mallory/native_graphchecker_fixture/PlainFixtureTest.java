package edu.uva.liftlab.graphchecker.runtime;

import static org.junit.Assert.assertEquals;
import org.junit.Test;

/** No GraphChecker or Mallory calls appear in this JUnit workload. */
public final class PlainFixtureTest {
    @Test public void healthyOperation() {
        assertEquals(2, new PlainFixture().run(1));
    }
}
