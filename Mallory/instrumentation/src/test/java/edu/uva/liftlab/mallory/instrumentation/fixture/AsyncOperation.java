package edu.uva.liftlab.mallory.instrumentation.fixture;

import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class AsyncOperation {
  public int run() throws Exception {
    ExecutorService executor = Executors.newSingleThreadExecutor();
    try {
      return executor.submit(new Callable<Integer>() {
        @Override public Integer call() { return 42; }
      }).get();
    } finally { executor.shutdownNow(); }
  }
}
