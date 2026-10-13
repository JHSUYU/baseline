package edu.uva.liftlab.mallory.graphchecker.weave.fixture;

public final class FixtureState {
    private int value = 1;

    public int read() { return value; }

    public void write(int next) { value = next; }
}
