package baseline.solr09;

import java.lang.reflect.Field;
import java.util.List;

/** Load the exact selector parser without starting a Solr cluster. */
public final class ProbeSmoke {
  public static void main(String[] args) throws Exception {
    System.setProperty("solr09.faults", String.join(";",
        "HTTP_POST|/admin/cores?action=UNLOAD&core=<target>|1|caller=org.apache.solr.handler.component.HttpShardHandler#submit|actor=target_replica_http",
        "GET_CHILDREN_STAT|/collections/deletereplica_test/state.json|@1|caller=org.apache.solr.common.cloud.ZkStateReader$StateWatcher#refreshAndWatchChildren|actor=target_command_reader|after=F0|seed_global=1",
        "GET_DATA|/collections/deletereplica_test/state.json|@2|caller=org.apache.solr.common.cloud.ZkStateReader#fetchCollectionState|actor=target_command_reader|after=F1|seed_global=2"));
    Field plans = FeedbackProbe.class.getDeclaredField("FAULTS");
    plans.setAccessible(true);
    List<?> faults = (List<?>) plans.get(null);
    if (faults.size() != 3) throw new IllegalStateException("expected three faults");
    String[] operations = {"HTTP_POST", "GET_CHILDREN_STAT", "GET_DATA"};
    for (int index = 0; index < operations.length; index++) {
      Field operation = faults.get(index).getClass().getDeclaredField("operation");
      operation.setAccessible(true);
      if (!operations[index].equals(operation.get(faults.get(index))))
        throw new IllegalStateException("fault order differs at " + index);
    }
    System.out.println("SOLR09_DIFF_SELECTOR_SMOKE PASS three ordered faults");
  }
}
