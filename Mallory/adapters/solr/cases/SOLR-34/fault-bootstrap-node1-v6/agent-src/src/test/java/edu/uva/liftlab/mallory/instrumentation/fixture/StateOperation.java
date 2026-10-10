package edu.uva.liftlab.mallory.instrumentation.fixture;

import java.util.HashMap;
import java.util.Map;

public final class StateOperation {
  private int number;
  private Map<String, Integer> values = new HashMap<String, Integer>();

  public int run(String key) {
    number = 3;
    int seen = number;
    values.put(key, seen);
    return values.get(key);
  }
}
