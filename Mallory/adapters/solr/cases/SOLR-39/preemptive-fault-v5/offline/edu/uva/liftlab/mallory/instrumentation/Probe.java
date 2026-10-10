package edu.uva.liftlab.mallory.instrumentation;

/** Offline gate control only: never packaged into the runtime adapter JAR. */
public final class Probe {
  public static int beforeCalls;
  public static int markerCalls;
  public static String lastResource;
  private Probe() { }
  public static String currentNode() { return "node2"; }
  public static int currentEpoch() { return 0; }
  public static String captureContext() { return "node2:0:test:watcher:1"; }
  public static void stateRead(Object manager, Object resource, String site) {
    markerCalls++;
    lastResource = String.valueOf(resource);
  }
  public static void beforeDoor(String site, String exception) { beforeCalls++; }
}
