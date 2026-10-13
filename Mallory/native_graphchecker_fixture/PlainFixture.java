package edu.uva.liftlab.graphchecker.runtime;

/** Unmodified workload class used to prove the original Soot weave. */
public final class PlainFixture {
    int value;

    public int run(int next) {
        value = next;
        if (value > 0) return 2;
        throw new IllegalStateException("fixture target");
    }
}
