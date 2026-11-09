/*
 * MC-3 reproduction helper. Copied by test_bugMC-3_late_register.sh to
 * hbase-server/src/test/java/org/apache/hadoop/hbase/regionserver/SpeculaMC3RegionServer.java
 * (RSRpcServices.stop() is package-private, hence this package).
 *
 * It uses the codebase's rsClass subclassing pattern and adds exactly two things, neither of which
 * touches the guard or its operands:
 *  1. CRASH: the codebase's simulated kill -9 (MiniHBaseClusterRegionServer.kill()), delivered while
 *     the first close call is on the wire (counterexample states 6-7). With holdZnode the exit path
 *     parks right after the RPC port closes and before deleteMyEphemeralNode(): the port is dead and
 *     the ZK session is alive, which is what a real kill -9 looks like until the ZK session expires.
 *     release() lets the exit continue, which deletes the znode: the session expiry.
 *  2. OBSERVE: executeProcedures() delegates to the real method and records the ServiceException
 *     thrown by the real RSRpcServices.throwOnWrongStartCode with its real stack trace.
 */
package org.apache.hadoop.hbase.regionserver;

import java.io.IOException;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hbase.DoNotRetryIOException;
import org.apache.hadoop.hbase.ServerName;
import org.apache.hadoop.hbase.SingleProcessHBaseCluster;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import org.apache.hbase.thirdparty.com.google.protobuf.RpcController;
import org.apache.hbase.thirdparty.com.google.protobuf.ServiceException;

import org.apache.hadoop.hbase.shaded.protobuf.generated.AdminProtos.ExecuteProceduresRequest;
import org.apache.hadoop.hbase.shaded.protobuf.generated.AdminProtos.ExecuteProceduresResponse;

public class SpeculaMC3RegionServer extends SingleProcessHBaseCluster.MiniHBaseClusterRegionServer {

  private static final Logger LOG = LoggerFactory.getLogger(SpeculaMC3RegionServer.class);

  /** The server that crashes when the first close reaches it. */
  public static volatile ServerName crashTarget;
  public static volatile boolean holdZnode;
  public static volatile CountDownLatch crashed = new CountDownLatch(1);
  public static volatile CountDownLatch portClosed = new CountDownLatch(1);
  public static volatile CountDownLatch release = new CountDownLatch(1);
  public static volatile CountDownLatch fired = new CountDownLatch(1);

  /** One entry per real exception thrown by the target: request kind and full stack trace. */
  public static final List<String> FIRES = new CopyOnWriteArrayList<>();

  public SpeculaMC3RegionServer(Configuration conf) throws IOException, InterruptedException {
    super(conf);
  }

  public static void reset(ServerName target, boolean hold) {
    crashed = new CountDownLatch(1);
    portClosed = new CountDownLatch(1);
    release = new CountDownLatch(1);
    fired = new CountDownLatch(1);
    FIRES.clear();
    holdZnode = hold;
    crashTarget = target;
  }

  @Override
  protected RSRpcServices createRpcServices() throws IOException {
    return new MC3RpcServices(this);
  }

  private void crash() {
    new Thread(this::kill, "MC3-kill-" + getServerName().getPort()).start();
  }

  private static final class MC3RpcServices extends RSRpcServices {

    private final SpeculaMC3RegionServer rs;

    MC3RpcServices(SpeculaMC3RegionServer rs) throws IOException {
      super(rs);
      this.rs = rs;
    }

    @Override
    void stop() {
      super.stop();
      if (rs.getServerName().equals(crashTarget)) {
        LOG.info("MC3|P_PORT_CLOSED {} holdZnode={}", rs.getServerName(), holdZnode);
        portClosed.countDown();
        if (holdZnode) {
          boolean interrupted = false;
          for (;;) {
            try {
              release.await();
              break;
            } catch (InterruptedException e) {
              interrupted = true;
            }
          }
          LOG.info("MC3|P_SESSION_EXPIRES {} (exit continues to deleteMyEphemeralNode)",
            rs.getServerName());
          if (interrupted) {
            Thread.currentThread().interrupt();
          }
        }
      }
    }

    @Override
    public ExecuteProceduresResponse executeProcedures(RpcController controller,
      ExecuteProceduresRequest request) throws ServiceException {
      if (
        rs.getServerName().equals(crashTarget) && request.getCloseRegionCount() > 0
          && crashed.getCount() > 0
      ) {
        // counterexample states 6-7: the close is on the wire, the server dies before serving it
        LOG.info("MC3|P_CRASH_WITH_CLOSE_ON_WIRE {}", rs.getServerName());
        crashed.countDown();
        rs.crash();
        try {
          portClosed.await(60, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
          Thread.currentThread().interrupt();
        }
        throw new ServiceException(new IOException("crashed before serving the close"));
      }
      try {
        return super.executeProcedures(controller, request);
      } catch (ServiceException e) {
        Throwable cause = e.getCause();
        if (
          cause instanceof DoNotRetryIOException && cause.getMessage() != null
            && cause.getMessage().contains("intended for a different server")
        ) {
          StringWriter sw = new StringWriter();
          e.printStackTrace(new PrintWriter(sw));
          String kind = "close=" + request.getCloseRegionCount() + " open="
            + request.getOpenRegionCount();
          FIRES.add(kind + "\n" + sw);
          LOG.info("MC3|TARGET_FIRED #{} on={} {} msg={}", FIRES.size(), rs.getServerName(), kind,
            cause.getMessage());
          fired.countDown();
        }
        throw e;
      }
    }
  }
}
