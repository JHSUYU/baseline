package edu.uva.liftlab.graphchecker.runtime;

import edu.uva.liftlab.graphchecker.contract.GapClass;
import edu.uva.liftlab.graphchecker.contract.GapKind;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/** Source lookup beside the original GraphChecker runtime. */
public final class HdfsRuntimeSource {
  private static final Map<String, Object> ANCHORS = new ConcurrentHashMap<>();

  private HdfsRuntimeSource() { }

  public static void registerAnchor(Object anchor) {
    SourceRef source = RuntimeTraceContext.sourceFor(anchor);
    if (source != null) ANCHORS.put(source.key(), anchor);
  }

  public static String currentSourceKey() {
    SourceRef source = RuntimeTraceContext.currentSource();
    return source == null ? "" : source.key();
  }

  public static void registerCurrentSourceAlias(Object alias) {
    if (alias == null) return;
    SourceRef source = RuntimeTraceContext.currentSource();
    if (source == null) return;
    Object anchor = ANCHORS.get(source.key());
    if (anchor == null) {
      RowRuntime.gap(GapKind.LINEAGE_LOST, GapClass.BLOCKING,
          alias.getClass().getName(),
          "HDFS IPC Call has a current source but no registered anchor");
      return;
    }
    MessageDoors.registerSourceAlias(alias, anchor);
  }
}
