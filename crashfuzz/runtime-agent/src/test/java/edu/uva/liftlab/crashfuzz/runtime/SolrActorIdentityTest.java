package edu.uva.liftlab.crashfuzz.runtime;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertTrue;

public class SolrActorIdentityTest {
    private static final String SITE = "<org.apache.solr.update.SolrCmdDistributor: void doRequest()>#u5";

    @Test
    public void executorIdentitySurvivesChangedPoolAndPort() {
        ActorIdentity.Resolution first = SolrActorIdentity.fromContext(
                "updateExecutor-79-thread-1-processing-n:127.0.0.1:34379_ "
                        + "x:collection1_shard1_replica_n2 c:collection1 s:shard1 r:core_node3",
                null, null, SITE);
        ActorIdentity.Resolution second = SolrActorIdentity.fromContext(
                "updateExecutor-42-thread-9-processing-n:127.0.0.1:44991_ "
                        + "x:collection1_shard1_replica_n2 c:collection1 s:shard1 r:core_node3",
                null, null, SITE);
        assertEquals("solr:update:replica:core_node3", first.logicalNodeId);
        assertEquals(first.logicalNodeId, second.logicalNodeId);
        assertFalse(first.gap);
    }

    @Test
    public void distinctReplicasCannotCollapseAcrossJettyThreads() {
        ActorIdentity.Resolution one = SolrActorIdentity.fromContext(
                "qtp1034174401-263", "r:core_node3", "x:collection1_shard1_replica_n2", SITE);
        ActorIdentity.Resolution two = SolrActorIdentity.fromContext(
                "qtp572393411-71", "r:core_node4", "x:collection1_shard2_replica_n1", SITE);
        assertNotEquals(one.logicalNodeId, two.logicalNodeId);
        assertEquals("solr:http:replica:core_node3", one.logicalNodeId);
        assertFalse(one.gap);
    }

    @Test
    public void unresolvedJettyRequestIsNotAnInjectableActor() {
        ActorIdentity.Resolution gap = SolrActorIdentity.fromContext(
                "qtp1034174401-263", null, null, SITE);
        assertTrue(gap.gap);
        assertEquals("solr:unresolved:" + SITE, gap.logicalNodeId);
    }
}
