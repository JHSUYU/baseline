package fixture;

import java.io.FileOutputStream;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

public final class TinyNode {
    private static int value;

    public static void main(String[] args) throws Exception {
        value = Integer.parseInt(args[1]);
        ExecutorService executor = Executors.newSingleThreadExecutor();
        executor.execute(new Runnable() {
            @Override public void run() { value = value + 1; }
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
