package research.solrforcev2;

/** Exercises the same receiver/path gate used at the transformed retry entry. */
public final class OfflineSmoke {
  public static void main(String[] args) {
    Object targetClient = new Object();
    Object wrongJettyClient = new Object();
    Probe.bindForSmoke(targetClient, "n:127.0.0.1:1_solr",
        "forceleader_lower_terms_collection", "shard1");
    check(Probe.eligibleForSmoke(targetClient,
        "/collections/forceleader_lower_terms_collection/terms/shard1"),
        "bound target client and shard rejected");
    check(!Probe.eligibleForSmoke(wrongJettyClient,
        "/collections/forceleader_lower_terms_collection/terms/shard1"),
        "wrong physical client accepted");
    check(!Probe.eligibleForSmoke(targetClient,
        "/collections/forceleader_lower_terms_collection/terms/shard2"),
        "wrong shard accepted");
    check(!Probe.eligibleForSmoke(targetClient,
        "/collections/other_collection/terms/shard1"),
        "wrong collection accepted");
    check(!Probe.eligibleForSmoke(targetClient, "/live_nodes/unrelated"),
        "unrelated path accepted");
    System.out.println("SOLR31_ACTOR_V2_OFFLINE_SMOKE passed=5");
  }

  private static void check(boolean condition, String message) {
    if (!condition) throw new AssertionError(message);
  }
}
