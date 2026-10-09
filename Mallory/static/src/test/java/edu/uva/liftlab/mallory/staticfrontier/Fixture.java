package edu.uva.liftlab.mallory.staticfrontier;

import java.io.IOException;
import java.util.HashMap;
import java.util.Map;

final class Fixture {
    private static final Map<String, String> keys = new HashMap<>();

    static void update() {
        keys.put("key", "value");
    }

    static String read(String id) throws IOException {
        if (id == null) throw new IOException("bad input");
        return keys.get(id);
    }

    static void check(String id) throws IOException {
        String value = read(id);
        if (value == null) throw new IllegalStateException("TARGET_MISSING_KEY");
    }
}
