package org.apache.hadoop.hbase.client;

import org.apache.yetus.audience.InterfaceAudience;

import org.apache.hadoop.hbase.ipc.GraphCheckerHBaseDoors;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/** Carries the submitting HBase client's causal scope to its worker task. */
@InterfaceAudience.Private
final class GraphCheckerContextThreadPoolExecutor extends ThreadPoolExecutor {
  GraphCheckerContextThreadPoolExecutor(int corePoolSize, int maximumPoolSize,
    long keepAliveTime, TimeUnit unit, BlockingQueue<Runnable> workQueue,
    ThreadFactory threadFactory) {
    super(corePoolSize, maximumPoolSize, keepAliveTime, unit, workQueue, threadFactory);
  }

  @Override
  public void execute(Runnable task) {
    final Object scope = GraphCheckerHBaseDoors.captureScope();
    super.execute(() -> {
      long token = GraphCheckerHBaseDoors.enterCarriedScope(scope, "HBASE_CLIENT_POOL", "execute");
      try {
        task.run();
      } finally {
        GraphCheckerHBaseDoors.exitCarriedScope(token);
      }
    });
  }
}
