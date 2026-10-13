package edu.uva.liftlab.mallory.graphchecker.weave.fixture;

public final class FixtureOperation {
    public int classify(int value) {
        if (value > 0) {
            throw new IllegalStateException("positive");
        }
        return value;
    }

    public int choose(int value) {
        switch (value) {
            case 1: return 11;
            default: return 22;
        }
    }
}
