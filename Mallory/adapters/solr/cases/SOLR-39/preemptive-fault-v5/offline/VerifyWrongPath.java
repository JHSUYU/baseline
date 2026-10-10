import edu.uva.liftlab.mallory.instrumentation.Probe;
import edu.uva.liftlab.mallory.solr.solr39.PreemptiveGate;

/** The actor and ordinal match; only the actual getData path changes. */
public final class VerifyWrongPath {
  public static void main(String[] args) {
    if (args.length != 1) throw new IllegalArgumentException("bad or good");
    Object manager = new Object();
    PreemptiveGate.published(true, manager);
    PreemptiveGate.read(new Object(), manager);
    String resource = "good".equals(args[0]) ? "/aliases.json" : "/not-aliases.json";
    PreemptiveGate.beforeDoor(manager, resource, PreemptiveGate.SITE,
        "org.apache.zookeeper.KeeperException$ConnectionLossException");
    if ("bad".equals(args[0])) {
      if (Probe.beforeCalls != 0 || Probe.markerCalls != 0)
        throw new AssertionError("wrong resource reached Probe");
      System.out.println("WRONG_PATH_FAIL_CLOSED_OK");
    } else {
      if (Probe.beforeCalls != 1 || Probe.markerCalls != 1 ||
          !"/aliases.json".equals(Probe.lastResource))
        throw new AssertionError("exact resource was not marked before Probe");
      System.out.println("EXACT_PATH_GATE_OK");
    }
  }
}
