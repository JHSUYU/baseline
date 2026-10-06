import java.lang.instrument.Instrumentation;

/** One case-local recorder for the adjacent B2/B3 and RS start-code guards. */
public final class HBaseTransitAgent {
  private HBaseTransitAgent() {}

  public static void premain(String args, Instrumentation instrumentation) {
    HBase10Agent.premain(args, instrumentation);
    HBase31Probe.premain(args, instrumentation);
  }
}
