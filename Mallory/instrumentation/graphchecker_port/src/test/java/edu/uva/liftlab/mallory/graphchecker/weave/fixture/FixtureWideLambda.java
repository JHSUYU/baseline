package edu.uva.liftlab.mallory.graphchecker.weave.fixture;

import java.util.function.LongUnaryOperator;

public final class FixtureWideLambda {
    public long compute(long captured) {
        LongUnaryOperator operation = value -> {
            try {
                return add(value, captured);
            } catch (IllegalStateException ignored) {
                return -1L;
            }
        };
        return operation.applyAsLong(3L);
    }

    private long add(long left, long right) {
        return left + right;
    }
}
