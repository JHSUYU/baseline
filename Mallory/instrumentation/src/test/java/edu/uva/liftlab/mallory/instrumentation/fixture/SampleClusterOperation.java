package edu.uva.liftlab.mallory.instrumentation.fixture;

import java.io.ByteArrayInputStream;
import java.io.IOException;

public final class SampleClusterOperation {
  public int run(int n) throws IOException {
    ByteArrayInputStream stream = new ByteArrayInputStream(new byte[] { 7 });
    int result = stream.read();
    if (n < 0 && result >= 0) throw new IllegalStateException("selected target");
    return result + n;
  }

  public static void main(String[] args) throws IOException {
    new SampleClusterOperation().run(Integer.parseInt(args[0]));
  }

  public int choose(int input) {
    switch (input) {
      case 1: return 11;
      case 2: return 22;
      default: return -1;
    }
  }
}
