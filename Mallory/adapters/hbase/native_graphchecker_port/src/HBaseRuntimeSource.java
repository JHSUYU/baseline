package edu.uva.liftlab.graphchecker.runtime;

import org.apache.yetus.audience.InterfaceAudience;
import edu.uva.liftlab.graphchecker.contract.GapClass;
import edu.uva.liftlab.graphchecker.contract.GapKind;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/** Narrow HBase source bridge; lives beside the original runtime by package. */
@InterfaceAudience.Private
public final class HBaseRuntimeSource {
  private static final Map<String, Object> ANCHORS = new ConcurrentHashMap<>();
  private HBaseRuntimeSource() { }

  public static void registerAnchor(Object anchor) {
    SourceRef source = RuntimeTraceContext.sourceFor(anchor);
    if (source != null) ANCHORS.putIfAbsent(source.key(), anchor);
  }

  public static String currentSourceKey() {
    SourceRef source = RuntimeTraceContext.currentSource();
    return source == null ? "" : source.key();
  }

  public static void registerCurrentSourceAlias(Object alias) {
    SourceRef source = RuntimeTraceContext.currentSource();
    if (alias != null && source != null) {
      Object anchor = ANCHORS.get(source.key());
      if (anchor != null) {
        MessageDoors.registerSourceAlias(alias, anchor);
      } else {
        RowRuntime.gap(GapKind.LINEAGE_LOST, GapClass.DIAGNOSTIC,
            alias.getClass().getName(),
            "HBase Call has a current source but no registered source anchor");
      }
    }
  }
}
