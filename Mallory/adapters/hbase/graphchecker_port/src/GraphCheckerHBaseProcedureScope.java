package org.apache.hadoop.hbase.procedure2;

import edu.uva.liftlab.mallory.graphchecker.runtime.MessageDoors;
import java.util.Collections;
import java.util.Map;
import java.util.WeakHashMap;

/** Carries the submitting request's source and causal scope into procedure workers. */
public final class GraphCheckerHBaseProcedureScope {
  private static final Map<Procedure<?>, Object> SCOPES =
    Collections.synchronizedMap(new WeakHashMap<Procedure<?>, Object>());

  private GraphCheckerHBaseProcedureScope() {
  }

  public static void capture(Procedure<?> procedure) {
    if (procedure == null || MessageDoors.currentSourceKey().isEmpty()) {
      MessageDoors.gap("HBASE_PROCEDURE_SUBMIT_UNATTRIBUTED", "ProcedureExecutor",
        "no registered source at procedure submission");
      return;
    }
    synchronized (SCOPES) {
      if (!SCOPES.containsKey(procedure)) {
        SCOPES.put(procedure, MessageDoors.captureScope());
      }
    }
  }

  public static long enter(Procedure<?> procedure) {
    Object scope = SCOPES.get(procedure);
    if (scope == null) {
      MessageDoors.gap("HBASE_PROCEDURE_SCOPE_MISSING", "ProcedureExecutor",
        "procedure was recovered or submitted without an observed source");
      return 0L;
    }
    return MessageDoors.enterCarriedScope(scope, "HBASE_PROCEDURE", procedure.getClass().getName());
  }

  public static void exit(long token) {
    MessageDoors.exitCarriedScope(token);
  }
}
