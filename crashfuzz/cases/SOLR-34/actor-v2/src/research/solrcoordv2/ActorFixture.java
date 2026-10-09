package research.solrcoordv2;

/** Offline identity gate: a different SolrZkClient receiver must be excluded. */
public final class ActorFixture {
  public static void main(String[] args) {
    Object coordinatorClient = new Object();
    Object otherJettyClient = new Object();
    Probe.targetEnter("test_coll", "127.0.0.1:12345_solr", coordinatorClient);
    if (!Probe.isExactRequestClient(coordinatorClient, true))
      throw new AssertionError("target client excluded");
    if (Probe.isExactRequestClient(otherJettyClient, true))
      throw new AssertionError("different client accepted");
    if (Probe.isExactRequestClient(coordinatorClient, false))
      throw new AssertionError("non-request I/O accepted");
    Probe.close();
    System.out.println("SOLR34_ACTOR_IDENTITY_OK");
  }
}
