package edu.uva.liftlab.mallory.hbase.zkmonitor;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.Test;

public class TrackerMonitorHooksTest {
  private static class FakeListener {
    final Object watcher = new Object();
  }
  private static final class FakeTracker extends FakeListener { }

  @Test public void callbackBindsItsRegisteredWatcherAndRestoresCaller() {
    FakeTracker tracker = new FakeTracker();
    Probe.registerNode(tracker.watcher, "rs0", 0);
    String previous = Probe.currentNode();
    try (TrackerMonitorHooks.Scope ignored = TrackerMonitorHooks.enterCallback(tracker)) {
      assertEquals("rs0", Probe.currentNode());
    }
    assertEquals(previous, Probe.currentNode());
  }

  @Test public void exactMonitorPublicationIsConsumedAfterWake() throws Exception {
    FakeTracker tracker = new FakeTracker();
    Probe.registerNode(tracker.watcher, "rs0", 0);
    CountDownLatch waiting = new CountDownLatch(1);
    AtomicBoolean claimed = new AtomicBoolean();
    Thread waiter = new Thread(() -> {
      try (Probe.NodeScope ignored = Probe.withNode("rs0", 0)) {
        synchronized (tracker) {
          TrackerMonitorHooks.beforeWait(tracker);
          waiting.countDown();
          tracker.wait(1000);
          claimed.set(TrackerMonitorHooks.afterWait(tracker));
        }
      } catch (InterruptedException e) {
        throw new AssertionError(e);
      }
    });
    waiter.start();
    assertTrue(waiting.await(2, TimeUnit.SECONDS));
    synchronized (tracker) {
      try (TrackerMonitorHooks.Scope ignored = TrackerMonitorHooks.enterCallback(tracker)) {
        tracker.notifyAll();
        TrackerMonitorHooks.publish(tracker, "test:nodeCreated");
      }
    }
    waiter.join(2000);
    assertFalse(waiter.isAlive());
    assertTrue(claimed.get());
  }

  @Test public void timeoutAndCancelledWaitNeverClaimAStaleCallback() {
    Object tracker = new Object();
    try (Probe.NodeScope ignored = Probe.withNode("rs1", 0)) {
      synchronized (tracker) {
        TrackerMonitorHooks.beforeWait(tracker);
        assertFalse(TrackerMonitorHooks.afterWait(tracker));
        TrackerMonitorHooks.beforeWait(tracker);
        TrackerMonitorHooks.cancelledWait(tracker);
        TrackerMonitorHooks.publish(tracker, "test:late-callback");
        assertFalse(TrackerMonitorHooks.afterWait(tracker));
      }
    }
  }

  @Test public void publicationForAnotherTrackerCannotBeClaimed() {
    Object awaited = new Object();
    Object other = new Object();
    try (Probe.NodeScope ignored = Probe.withNode("rs2", 0)) {
      synchronized (awaited) { TrackerMonitorHooks.beforeWait(awaited); }
      synchronized (other) { TrackerMonitorHooks.publish(other, "test:other"); }
      synchronized (awaited) { assertFalse(TrackerMonitorHooks.afterWait(awaited)); }
    }
  }
}
