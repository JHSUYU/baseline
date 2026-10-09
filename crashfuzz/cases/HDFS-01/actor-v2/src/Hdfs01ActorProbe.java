import java.io.BufferedWriter;
import java.io.FileWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.apache.hadoop.hdfs.protocol.DatanodeID;
import org.apache.hadoop.hdfs.protocol.DatanodeInfoWithStorage;
import org.apache.hadoop.hdfs.protocol.LocatedBlock;
import org.apache.hadoop.hdfs.protocol.LocatedBlocks;

/** Actor-aware recorder for the unchanged TestPread MiniDFSCluster JUnit. */
public final class Hdfs01ActorProbe {
  private static final String TRACE = System.getProperty("hdfs01.actor.trace", "");
  private static final String PLAN = System.getProperty("hdfs01.actor.plan", "");
  private static final Map<String, Integer> HITS = new HashMap<>();
  private static final List<String[]> FAULTS = new ArrayList<>();
  private static final Map<Long, BlockActor> BLOCK_ACTORS = new HashMap<>();
  private static final ThreadLocal<String> LAST_TARGET = new ThreadLocal<>();
  private static BufferedWriter writer;
  private static long seq;
  private static int nextFault;

  private static final class BlockActor {
    final String file;
    final long startOffset;
    final Map<String, Integer> replicaByUuid = new HashMap<>();

    BlockActor(String file, LocatedBlock block) {
      this.file = file;
      this.startOffset = block.getStartOffset();
      DatanodeInfoWithStorage[] locations = block.getLocations();
      for (int index = 0; index < locations.length; index++) {
        String uuid = locations[index].getDatanodeUuid();
        if (uuid != null && !uuid.isEmpty()) {
          replicaByUuid.put(uuid, index);
        }
      }
    }
  }

  static {
    try {
      if (!TRACE.isEmpty()) writer = new BufferedWriter(new FileWriter(TRACE));
      if (!PLAN.isEmpty()) {
        for (String line : Files.readAllLines(Paths.get(PLAN), StandardCharsets.UTF_8)) {
          if (!line.isEmpty() && !line.startsWith("#")) {
            String[] fault = line.split("\t", -1);
            if (fault.length != 7 || fault[2].isEmpty() || !fault[5].equals("pending")
                || !(fault[6].equals("IOException")
                    || fault[6].equals("EOFException")
                    || fault[6].equals("SocketTimeoutException"))) {
              throw new IllegalArgumentException("invalid actor-aware fault plan: " + line);
            }
            Integer.parseInt(fault[4]);
            FAULTS.add(fault);
          }
        }
      }
      Runtime.getRuntime().addShutdownHook(new Thread(() -> {
        synchronized (Hdfs01ActorProbe.class) {
          try { if (writer != null) writer.close(); } catch (IOException ignored) { }
        }
      }));
    } catch (IOException ex) { throw new ExceptionInInitializerError(ex); }
  }

  private Hdfs01ActorProbe() { }

  private static String q(String s) {
    return "\"" + String.valueOf(s).replace("\\", "\\\\").replace("\"", "\\\"")
        .replace("\n", "\\n").replace("\r", "\\r") + "\"";
  }

  private static void emit(String event, String fields) {
    synchronized (Hdfs01ActorProbe.class) {
      if (writer == null) return;
      try {
        writer.write("{\"event\":" + q(event) + ",\"seq\":" + (++seq)
            + ",\"thread\":" + q(Thread.currentThread().getName()) + fields + "}\n");
        writer.flush();
      } catch (IOException ex) { throw new RuntimeException(ex); }
    }
  }

  private static void rememberBlocks(LocatedBlocks blocks, String file,
      String origin) {
    if (blocks != null && blocks.getLocatedBlocks() != null) {
      for (LocatedBlock block : blocks.getLocatedBlocks()) {
        BlockActor actor = new BlockActor(file, block);
        if (!actor.replicaByUuid.isEmpty()) {
          BLOCK_ACTORS.put(block.getBlock().getBlockId(), actor);
          for (Map.Entry<String, Integer> replica : actor.replicaByUuid.entrySet()) {
            emit("BLOCK_LOCATION", ",\"origin\":" + q(origin) +
                ",\"file\":" + q(file) +
                ",\"blockId\":" + block.getBlock().getBlockId() +
                ",\"startOffset\":" + actor.startOffset +
                ",\"actorUuid\":" + q(replica.getKey()) +
                ",\"replicaIndex\":" + replica.getValue());
          }
        }
      }
    }
  }

  /** The open-file response includes the first block, before fetchBlockAt. */
  public static synchronized void locatedBlocks(LocatedBlocks blocks, String file) {
    rememberBlocks(blocks, file, "RPC_RETURN");
    emit("BLOCK_LOCATIONS", ",\"file\":" + q(file) +
        ",\"blockCount\":" +
        (blocks == null ? -1 : blocks.locatedBlockCount()));
  }

  /** Called immediately before the selected IFNULL in fetchBlockAt. */
  public static synchronized void targetCheck(LocatedBlocks blocks, long offset,
      String file) {
    int count = blocks == null ? -1 : blocks.locatedBlockCount();
    rememberBlocks(blocks, file, "TARGET_GUARD");
    String context = ",\"file\":" + q(file) + ",\"offset\":" + offset;
    LAST_TARGET.set(context);
    emit("TARGET_CHECK", ",\"siteId\":\"DFSInputStream.fetchBlockAt#L517-B5\""
        + context + ",\"blockCount\":" + count
        + ",\"wouldThrow\":" + (count <= 0));
  }

  public static void targetThrow(Throwable ex) {
    emit("TARGET_THROW", ",\"siteId\":\"DFSInputStream.fetchBlockAt#L518\""
        + (LAST_TARGET.get() == null ? "" : LAST_TARGET.get())
        + ",\"exception\":" + q(ex.getClass().getName())
        + ",\"message\":" + q(ex.getMessage()));
  }

  /** Client-side operations in this JUnit talk to its single NameNode. */
  public static void io(String marker, String site) throws IOException {
    String source = Thread.currentThread().getName();
    observe(marker, site, source, source, "", "", -1L);
  }

  /** Bind a read to the live DataNode UUID and the block's response position. */
  public static void readIo(DatanodeID datanode, long blockId, String file)
      throws IOException {
    String uuid = datanode == null ? "" : datanode.getDatanodeUuid();
    BlockActor block;
    synchronized (Hdfs01ActorProbe.class) {
      block = BLOCK_ACTORS.get(blockId);
    }
    boolean bound = block != null && block.file.equals(file)
        && block.replicaByUuid.containsKey(uuid);
    String actor = bound ? "replica:" + block.replicaByUuid.get(uuid) : "";
    String resource = bound ? file + "@" + block.startOffset : "";
    observe("FAULT:HDFS_DATA_TRANSFER:READ", "BlockReaderRemote.read",
        Thread.currentThread().getName(), actor, resource, uuid, blockId);
  }

  private static synchronized void observe(String marker, String site, String source,
      String actor, String resource, String uuid, long blockId)
      throws IOException {
    String key = marker + "|" + site + "|" + actor + "|" + resource;
    int ordinal = HITS.containsKey(key) ? HITS.get(key) + 1 : 1;
    HITS.put(key, ordinal);
    String fields = ",\"marker\":" + q(marker) + ",\"siteId\":" + q(site)
        + ",\"sourceKey\":" + q(source) + ",\"occurrence\":" + q(source + "/" + site)
        + ",\"actorKey\":" + q(actor) + ",\"resourceKey\":" + q(resource)
        + ",\"actorUuid\":" + q(uuid) + ",\"blockId\":" + blockId
        + ",\"identityBound\":" + !actor.isEmpty()
        + ",\"hitOrdinal\":" + ordinal;
    emit("FAULT_POINT_OBSERVED", fields);
    if (actor.isEmpty() || nextFault == FAULTS.size()) return;
    String[] fault = FAULTS.get(nextFault);
    if (fault.length != 7 || !fault[0].equals(marker)
        || !fault[1].equals(site) || !fault[2].equals(actor)
        || !fault[3].equals(resource)
        || Integer.parseInt(fault[4]) != ordinal) return;
    int faultIndex = nextFault++;
    fault[5] = "applied";
    String kind = fault[6];
    emit("FAULT_MATCHED", fields + ",\"faultIndex\":" + faultIndex + ",\"faultType\":" + q(kind));
    emit("FAULT_APPLIED", fields + ",\"faultIndex\":" + faultIndex + ",\"faultType\":" + q(kind));
    String message = "HDFS-01 injected " + kind + " at " + site + ":" + ordinal;
    if (kind.equals("SocketTimeoutException")) throw new java.net.SocketTimeoutException(message);
    if (kind.equals("EOFException")) throw new java.io.EOFException(message);
    if (!kind.equals("IOException")) throw new IllegalArgumentException("Unknown fault: " + kind);
    throw new IOException(message);
  }
}
