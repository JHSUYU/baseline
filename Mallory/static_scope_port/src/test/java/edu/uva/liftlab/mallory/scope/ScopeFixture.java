package edu.uva.liftlab.mallory.scope;

import java.io.IOException;
import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.util.concurrent.Callable;
import java.util.concurrent.Executor;

final class ScopeFixture {
    static final class Box { String value; }
    static final class Job implements Callable<String>, Runnable {
        @Override public String call() { return read(); }
        @Override public void run() {
            if (read() == null) throw new IllegalStateException("CALLBACK_TARGET");
        }
    }
    static volatile String shared;

    static void update(String value) {
        shared = value;
    }

    static String read() {
        return shared;
    }

    static String send(String value) throws IOException {
        return value;
    }

    static String receive(String value) {
        return value;
    }

    static void check() throws IOException {
        String answer = receive(send(read()));
        if (answer == null) throw new IOException("SCOPE_TARGET");
    }

    static void afterCatch() throws IOException {
        try {
            send("unrelated");
        } catch (IOException ignored) {
            ignored.getMessage();
        }
        if (read() == null) throw new IOException("AFTER_CATCH_TARGET");
    }

    static void checkDistinctBox() throws IOException {
        Box wanted = new Box();
        Box unrelated = new Box();
        wanted.value = "present";
        unrelated.value = "other";
        if (wanted.value == null) throw new IOException("BOX_TARGET");
    }

    static void checkCallable() throws Exception {
        Callable<String> job = new Job();
        if (job.call() == null) throw new IOException("CALLABLE_TARGET");
    }

    static void schedule(Executor executor) {
        executor.execute(new Job());
    }

    static void checkLambdaCallable() throws Exception {
        Callable<String> selected = () -> read();
        Callable<String> unrelated = () -> "other";
        if (selected.call() == null) throw new IOException("LAMBDA_TARGET");
        unrelated.hashCode();
    }

    static void checkReader(BufferedReader reader) throws IOException {
        String value = reader.readLine();
        if (value == null) throw new IOException("READ_TARGET");
    }

    static void checkFileReader(File file) throws IOException {
        BufferedReader reader = new BufferedReader(new FileReader(file));
        if (reader.readLine() == null) throw new IOException("FILE_READ_TARGET");
    }

    static void checkHelperDoor(BufferedReader reader) throws IOException {
        if (GraphCheckerFixtureHelper.read(reader) == null) {
            throw new IOException("HELPER_TARGET");
        }
    }

    static void checkCompoundAssert(boolean leader, boolean pull) {
        assert !(leader && pull) : "COMPOUND_ASSERT_TARGET";
    }

    static void checkCompoundOr(boolean first, boolean second) throws IOException {
        if (first || second) throw new IOException("COMPOUND_OR_TARGET");
    }

    static void checkAmbiguousSameLine(boolean first, boolean second) throws IOException {
        if (first) throw new IOException("AMBIGUOUS_TARGET"); if (second) throw new IOException("other");
    }

    static void checkBlockPoolLike(boolean running) throws IOException {
        if (running) {
            throw new IOException("BLOCK_POOL_TARGET");
        }
    }

    static void helperCheckState(boolean valid) {
        if (!valid) throw new IllegalStateException("CALL_THROW_TARGET");
    }

    static void checkCalledState(Object first, Object second) {
        boolean valid = first == second; // CALL_THROW_CHECK
        helperCheckState(valid); // CALL_THROW_SITE
    }

    static void checkCalledStateWithFallback(Object first, Object second,
                                              Object referred) {
        boolean identity = first == second; // CALL_THROW_FALLBACK_CHECK
        boolean valid = identity || first == referred;
        helperCheckState(valid); // CALL_THROW_FALLBACK_SITE
    }

    static void checkCalledStateBothArmsFail(boolean flag) {
        boolean valid;
        if (flag) valid = false; else valid = false; // CALL_THROW_AMBIGUOUS_CHECK
        helperCheckState(valid); // CALL_THROW_AMBIGUOUS_SITE
    }
}
