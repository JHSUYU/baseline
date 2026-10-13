package org.apache.hadoop.hbase.procedure2;

import org.apache.yetus.audience.InterfaceAudience;

import edu.uva.liftlab.graphchecker.contract.GapClass;
import edu.uva.liftlab.graphchecker.contract.GapKind;
import edu.uva.liftlab.graphchecker.runtime.MessageDoors;
import edu.uva.liftlab.graphchecker.runtime.RowRuntime;
import java.util.Collections;
import java.util.Map;
import java.util.WeakHashMap;

/** Carries the submitting request's source and causal scope into procedure workers. */
@InterfaceAudience.Private
public final class GraphCheckerHBaseProcedureScope {
  private static final Map<Procedure<?>, Object> SCOPES =
    Collections.synchronizedMap(new WeakHashMap<Procedure<?>, Object>());

  private GraphCheckerHBaseProcedureScope() {
  }

  public static void capture(Procedure<?> procedure) {
    if (procedure == null) return;
    synchronized (SCOPES) {
      if (!SCOPES.containsKey(procedure)) {
        SCOPES.put(procedure, MessageDoors.captureScope());
      }
    }
  }

  public static long enter(Procedure<?> procedure) {
    Object scope = SCOPES.get(procedure);
    if (scope == null) {
      RowRuntime.gap(GapKind.LINEAGE_LOST, GapClass.DIAGNOSTIC,
        "ProcedureExecutor", "procedure had no observed submission scope");
      return 0L;
    }
    long token = MessageDoors.enterCarriedScope(scope, "HBASE_PROCEDURE",
        procedure.getClass().getName());
    if (token == 0L) RowRuntime.gap(GapKind.LINEAGE_LOST, GapClass.DIAGNOSTIC,
        "ProcedureExecutor", "observed submission scope had no named source");
    return token;
  }

  public static void exit(long token) {
    MessageDoors.exitCarriedScope(token);
  }
}
