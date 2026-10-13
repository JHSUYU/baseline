package edu.uva.liftlab.mallory.graphchecker.weave.fixture;

import static org.junit.Assert.assertEquals;
import org.junit.Test;

public final class FixtureCatchLiveIntJUnit {
    @Test public void originalCatchReadsLiveInt() {
        assertEquals(3, new FixtureCatchLiveInt().parse("bad"));
    }
}
