package edu.uva.liftlab.mallory.graphchecker.weave.fixture;

import static org.junit.Assert.assertEquals;
import org.junit.Test;

public final class FixtureWideLambdaJUnit {
    @Test public void originalWideLambda() {
        assertEquals(12L, new FixtureWideLambda().compute(9L));
    }
}
