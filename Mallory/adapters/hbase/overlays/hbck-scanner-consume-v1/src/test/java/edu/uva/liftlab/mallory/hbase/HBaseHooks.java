package edu.uva.liftlab.mallory.hbase;

import java.util.Collections;
import java.util.Map;
import java.util.WeakHashMap;

/** Test-only stand-in for the existing adapter's private, future-keyed token registry. */
public final class HBaseHooks {
  private static final Map<Object, ScannerTokens> SCANNER_TOKENS =
      Collections.synchronizedMap(new WeakHashMap<Object, ScannerTokens>());

  private HBaseHooks() { }

  public static void set(Object future, String token, boolean published) {
    SCANNER_TOKENS.put(future, new ScannerTokens(token, published));
  }

  private static final class ScannerTokens {
    private final String result;
    private final boolean resultPublished;
    private ScannerTokens(String result, boolean resultPublished) {
      this.result = result;
      this.resultPublished = resultPublished;
    }
  }
}
