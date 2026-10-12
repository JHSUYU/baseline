package edu.uva.liftlab.crashfuzz.staticselection;

import java.io.FileOutputStream;
import java.io.FileInputStream;
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
    static int watchedValue;
    static int protocolValue;

    public static final class ProtocolException extends IOException {
        public ProtocolException(String message) { super(message); }
    }

    public static final class Protocol {
        public static int read() throws IOException {
            return ProtocolParser.parse();
        }
    }

    public static final class ProtocolParser {
        public static int parse() throws IOException {
            throw new ProtocolException("remote rejected key");
        }
    }

    public static final class ProtocolUser {
        public void check() {
            if (protocolValue == 7) throw new IllegalStateException("protocol target");
        }

        public void update() throws IOException {
            protocolValue = Protocol.read();
        }
    }

    public static final class Reader {
        public void check() {
            keys.get(1);
            if (shared == 7) throw new IllegalStateException("target");
        }
    }

    public static final class ThrowLineReader {
        public void check() {
            if (shared == 7) {
                throw new IllegalStateException("target on a later source line");
            }
        }
    }

    public static final class WatchedReader {
        public void check() {
            if (watchedValue == 7) throw new IllegalStateException("watch target");
        }
    }

    public static final class WatchOwner {
        private static void fetch() {
            try (FileInputStream file = new FileInputStream("/tmp/watch-state")) {
                file.read();
            } catch (IOException ignored) {
                // This fixture is analyzed, never executed.
            }
        }

        public static final class Callback {
            public void process() {
                watchedValue = 7;
                fetch();
            }
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

    public static final class WireTarget {
        public void check(boolean bad) {
            if (bad) throw new IllegalStateException("wire target");
        }
    }

    public static final class WireValueSource {
        public int encode() {
            return 7;
        }
    }

    public static final class WireSender {
        public int first() { return new WireValueSource().encode(); }
        public int second() { return first(); }
        public int third() { return second(); }
        public int fourth() { return third(); }
        public int fifth() throws IOException {
            try (FileOutputStream file = new FileOutputStream("/tmp/wire-sender")) {
                file.write(1);
            }
            return fourth();
        }
    }
}
