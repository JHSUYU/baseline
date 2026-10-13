package edu.uva.liftlab.mallory.graphchecker.weave.fixture;

import edu.uva.liftlab.mallory.graphchecker.runtime.MessageDoors;

public final class FixtureScopeBoundary {
    private static final Object INNER = new Object();
    private static long innerRequest;

    public int run() {
        begin();
        try {
            return 5;
        } finally {
            end();
        }
    }

    private static void begin() {
        MessageDoors.registerNode(INNER, "FIXTURE", "SERVER", "fixture-inner");
        innerRequest = MessageDoors.beginRequest(INNER, "inner");
    }

    private static void end() {
        MessageDoors.endRequest(innerRequest, "inner");
    }
}
