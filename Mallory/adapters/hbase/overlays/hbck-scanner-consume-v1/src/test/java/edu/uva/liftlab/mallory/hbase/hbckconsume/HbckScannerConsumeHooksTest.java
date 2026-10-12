package edu.uva.liftlab.mallory.hbase.hbckconsume;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

import edu.uva.liftlab.mallory.hbase.HBaseHooks;
import edu.uva.liftlab.mallory.instrumentation.Probe;
import org.apache.hadoop.hbase.client.Result;
import org.apache.hadoop.hbase.util.Pair;
import org.junit.Test;

public class HbckScannerConsumeHooksTest {
  @Test public void claimsOnlyConsumedResultIdentityAndRestoresContext() {
    Object future = new Object();
    HBaseHooks.set(future, "future-token-a", true);
    Result row = new Result(7);
    Result equalButDifferent = new Result(7);
    HbckScannerConsumeHooks.futureValueReturned(future, new Pair<>(new Result[] { row }));
    assertNull(HbckScannerConsumeHooks.enterConsumedResult(equalButDifferent));
    String before = Probe.captureContext();
    try (Probe.ContextScope scope = HbckScannerConsumeHooks.enterConsumedResult(row)) {
      assertEquals("future-token-a", Probe.captureContext());
    }
    assertEquals(before, Probe.captureContext());
    assertNull(HbckScannerConsumeHooks.enterConsumedResult(row));
  }

  @Test public void unpublishedFutureAndUnknownValueCannotCreateEdge() {
    Object future = new Object();
    HBaseHooks.set(future, "future-token-b", false);
    Result row = new Result(8);
    HbckScannerConsumeHooks.futureValueReturned(future, new Pair<>(new Result[] { row }));
    assertNull(HbckScannerConsumeHooks.enterConsumedResult(row));
    HbckScannerConsumeHooks.futureValueReturned(new Object(), new Pair<>(new Result[] { row }));
    assertNull(HbckScannerConsumeHooks.enterConsumedResult(row));
  }

  @Test public void twoFutureTokensForSameResultAreAmbiguous() {
    Result row = new Result(9);
    Object first = new Object();
    Object second = new Object();
    HBaseHooks.set(first, "future-token-c", true);
    HBaseHooks.set(second, "future-token-d", true);
    HbckScannerConsumeHooks.futureValueReturned(first, new Pair<>(new Result[] { row }));
    HbckScannerConsumeHooks.futureValueReturned(second, new Pair<>(new Result[] { row }));
    assertNull(HbckScannerConsumeHooks.enterConsumedResult(row));
  }

  @Test public void aReturnedArrayWithNoExactResultIdentityDoesNotTransfer() {
    Object future = new Object();
    HBaseHooks.set(future, "future-token-e", true);
    Result input = new Result(10);
    Result reconstructedCacheRow = new Result(10);
    HbckScannerConsumeHooks.futureValueReturned(future, new Pair<>(new Result[] { input }));
    assertNull(HbckScannerConsumeHooks.enterConsumedResult(reconstructedCacheRow));
  }
}
