package edu.uva.liftlab.mallory.hbase.hbckconsume;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import org.apache.hadoop.hbase.client.Result;
import org.apache.hadoop.hbase.util.Pair;
import org.junit.Test;

public class HbckScannerConsumeHooksTest {
  private static final class FutureValue {
    private final Object result;
    private final boolean resultObtained;
    FutureValue(Object result, boolean obtained) {
      this.result = result;
      this.resultObtained = obtained;
    }
  }

  @Test public void publishesOneTokenPerRowAndClaimsEachOnce() {
    Result first = new Result(7);
    Result second = new Result(8);
    FutureValue future = new FutureValue(new Pair<>(new Result[] { first, second }), true);
    HbckScannerConsumeHooks.publishFutureRows(future);
    HbckScannerConsumeHooks.publishFutureRows(future); // multiple bytecode notify exits
    String before = Probe.captureContext();
    String firstToken;
    try (Probe.ContextScope scope = HbckScannerConsumeHooks.enterConsumedResult(first)) {
      assertNotNull(scope);
      firstToken = Probe.captureContext();
      assertNotEquals(before, firstToken);
    }
    assertEquals(before, Probe.captureContext());
    try (Probe.ContextScope scope = HbckScannerConsumeHooks.enterConsumedResult(second)) {
      assertNotNull(scope);
      assertNotEquals(firstToken, Probe.captureContext());
    }
    assertNull(HbckScannerConsumeHooks.enterConsumedResult(first));
    assertNull(HbckScannerConsumeHooks.enterConsumedResult(second));
  }

  @Test public void equalButDifferentResultHasNoToken() {
    Result row = new Result(9);
    HbckScannerConsumeHooks.publishFutureRows(
        new FutureValue(new Pair<>(new Result[] { row }), true));
    assertNull(HbckScannerConsumeHooks.enterConsumedResult(new Result(9)));
    assertNotNull(HbckScannerConsumeHooks.enterConsumedResult(row));
  }

  @Test public void unsuccessfulAndUnknownFutureCannotPublish() {
    Result row = new Result(10);
    HbckScannerConsumeHooks.publishFutureRows(
        new FutureValue(new Pair<>(new Result[] { row }), false));
    assertNull(HbckScannerConsumeHooks.enterConsumedResult(row));
    HbckScannerConsumeHooks.publishFutureRows(new Object());
    assertNull(HbckScannerConsumeHooks.enterConsumedResult(row));
  }

  @Test public void duplicateResultIdentityWithinOrAcrossFuturesFailsClosed() {
    Result repeated = new Result(11);
    HbckScannerConsumeHooks.publishFutureRows(
        new FutureValue(new Pair<>(new Result[] { repeated, repeated }), true));
    assertNull(HbckScannerConsumeHooks.enterConsumedResult(repeated));
    Result shared = new Result(12);
    HbckScannerConsumeHooks.publishFutureRows(
        new FutureValue(new Pair<>(new Result[] { shared }), true));
    HbckScannerConsumeHooks.publishFutureRows(
        new FutureValue(new Pair<>(new Result[] { shared }), true));
    assertNull(HbckScannerConsumeHooks.enterConsumedResult(shared));
  }

  @Test public void reconstructedCacheRowHasNoIdentityLink() {
    Result input = new Result(13);
    HbckScannerConsumeHooks.publishFutureRows(
        new FutureValue(new Pair<>(new Result[] { input }), true));
    assertNull(HbckScannerConsumeHooks.enterConsumedResult(new Result(13)));
  }
}
