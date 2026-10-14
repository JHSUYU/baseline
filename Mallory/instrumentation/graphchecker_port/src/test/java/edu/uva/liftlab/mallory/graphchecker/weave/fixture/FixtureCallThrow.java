package edu.uva.liftlab.mallory.graphchecker.weave.fixture;

public final class FixtureCallThrow {
    public static int factory(boolean ok) {
        if (!ok) throw makeFailure();
        return 1;
    }

    private static IllegalStateException makeFailure() {
        return new IllegalStateException("factory failure");
    }
}
