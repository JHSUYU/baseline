package baseline.solr103940;

import java.nio.charset.StandardCharsets;
import org.apache.zookeeper.KeeperException;

/** Two live clients: a producer writes the precise alias read by another node. */
public final class CrossAliasSmoke {
  public static void main(String[] args) throws Exception {
    Object writer = new Object();
    Object reader = new Object();
    Object writerManager = new Object();
    Object readerManager = new Object();
    FeedbackProbe.registerNode(writer, writerManager, "127.0.0.1:12345_solr");
    FeedbackProbe.registerNode(reader, readerManager, "127.0.0.1:23456_solr");
    FeedbackProbe.registerJettyRole("node1", "127.0.0.1:12345_solr");
    FeedbackProbe.registerJettyRole("node2", "127.0.0.1:23456_solr");
    byte[] aliases = ("{\"collection\":{\"myalias\":\"myalias__TRA__2017-10-23\","
        + "\"myalias2\":\"other\"}}").getBytes(StandardCharsets.UTF_8);
    try {
      FeedbackProbe.io("SET_DATA", "/aliases.json", writer, aliases);
      throw new AssertionError("Selected alias producer was not injected");
    } catch (KeeperException.ConnectionLossException expected) {
      // Fault before the producer writes to the shared aliases znode.
    }
    FeedbackProbe.targetCheck(false, "SOLR-39", "myalias", "remote reader", reader,
        readerManager, "127.0.0.1:23456_solr");
    FeedbackProbe.targetCheck(false, "SOLR-40", "otherAlias", "unrelated reader", reader,
        readerManager, "127.0.0.1:23456_solr");
    System.out.println("SOLR103940_V2_CROSS_ALIAS_SMOKE_PASS");
  }
}
