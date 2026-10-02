package fixture;

import java.io.FileOutputStream;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

public final class TinyNode {
    private static int value;

    private static int increment(int current) {
        if (current == 0) return 1;
        return current + 1;
    }

    public static void main(String[] args) throws Exception {
        value = Integer.parseInt(args[1]);
        ExecutorService executor = Executors.newSingleThreadExecutor();
        executor.execute(new Runnable() {
            @Override public void run() { value = increment(value); }
        });
        executor.shutdown();
        executor.awaitTermination(5, TimeUnit.SECONDS);
        try (FileOutputStream out = new FileOutputStream(args[0])) {
            out.write(1);
        }
        if (value < 0) {
            throw new IllegalStateException("target failure");
        }
    }
}
