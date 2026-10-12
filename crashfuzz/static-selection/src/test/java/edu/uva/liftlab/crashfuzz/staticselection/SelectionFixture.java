package edu.uva.liftlab.crashfuzz.staticselection;

import java.io.FileOutputStream;
import java.io.IOException;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.Executor;

public final class SelectionFixture {
    private SelectionFixture() {}

    public static void main(String[] args) {
        new Writer().run();
        try {
            new Reader().check();
        } catch (IllegalStateException expected) {
            // The target probe must report this checked exception outcome.
        }
    }

    static int shared;
    static final Map<Integer, Integer> keys = new HashMap<>();

    public static final class Reader {
        public void check() {
            keys.get(1);
            if (shared == 7) throw new IllegalStateException("target");
        }
    }

    public static final class Writer implements Runnable {
        @Override public void run() {
            shared = 7;
            keys.put(1, 7);
            try (FileOutputStream file = new FileOutputStream("/tmp/selection-fixture")) {
                file.write(1);
            } catch (IOException ignored) {
                // This fixture is analyzed, never executed.
            }
        }
    }

    public static final class MapWriter {
        public void update() {
            keys.put(2, 8);
        }
    }

    public static final class Wrapper {
        public void install() {
            new MapWriter().update();
        }
    }

    public static final class RpcHandler {
        public void receive() {
            new Wrapper().install();
        }
    }

    public static final class Actor {
        public void run() {
            sendHeartbeat();
            new RpcHandler().receive();
        }

        private void sendHeartbeat() {
            try (FileOutputStream file = new FileOutputStream("/tmp/actor-heartbeat")) {
                file.write(1);
            } catch (IOException ignored) {
                // This fixture is analyzed, never executed.
            }
        }
    }

    public static final class Launcher {
        public void launch(Executor executor) {
            executor.execute(new Writer());
        }
    }

    public static final class RpcProducer {
        public void send() {
            shared = 1;
        }
    }
}
