package edu.uva.liftlab.mallory.instrumentation.fixture;

public final class CallGuardOperation {
  public static final IllegalArgumentException EXPECTED = new IllegalArgumentException("guard");
  public static Throwable caught;

  public static void requirePositive(boolean valid) {
    if (!valid) throw EXPECTED;
  }

  public int run(int value) {
    try {
      requirePositive(value > 0);
      return value;
    } catch (IllegalArgumentException failure) {
      caught = failure;
      return -1;
    }
  }

  public static final class Constructed {
    public Constructed(int value) {
      requirePositive(value > 0);
    }
  }
}
