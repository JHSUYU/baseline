package edu.uva.liftlab.mallory.graphchecker.runtime;

/** Fresh JVM keeps the fixture independent of other runtime tests' static recorder state. */
public final class UnattributedRegionGapFixture {
    public static void main(String[] args) {
        System.setProperty("mallory.graphchecker.trace.file", args[0]);
        MessageDoors.startRecording();
        for (int i = 0; i < 50; i++) {
            if (TraceRows.enterRegion("R.loop", "", 0)) {
                throw new AssertionError("unattributed region entered");
            }
        }
        TraceRows.gap("WIRE_HEADER_MISSING", "http", "unrelated");
        TraceRows.gap("WIRE_HEADER_MISSING", "http", "unrelated");
        MessageDoors.stopRecording();
        TraceRows.close();
    }
}
