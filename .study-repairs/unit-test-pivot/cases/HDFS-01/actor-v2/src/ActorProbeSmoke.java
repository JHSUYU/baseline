import java.io.EOFException;
import java.io.IOException;
import java.util.Arrays;
import org.apache.hadoop.hdfs.protocol.DatanodeID;
import org.apache.hadoop.hdfs.protocol.DatanodeInfo;
import org.apache.hadoop.hdfs.protocol.ExtendedBlock;
import org.apache.hadoop.hdfs.protocol.LocatedBlock;
import org.apache.hadoop.hdfs.protocol.LocatedBlocks;

/** Exercises live UUID binding and ordered faults without starting a cluster. */
public final class ActorProbeSmoke {
  public static void main(String[] args) throws Exception {
    DatanodeID first = new DatanodeID("127.0.0.1", "localhost", "uuid-a",
        50010, 50075, 50475, 50020);
    DatanodeID other = new DatanodeID("127.0.0.2", "localhost", "uuid-b",
        50011, 50076, 50476, 50021);
    DatanodeInfo firstInfo = new DatanodeInfo.DatanodeInfoBuilder()
        .setNodeID(first).build();
    LocatedBlock block = new LocatedBlock(new ExtendedBlock("BP-smoke", 42L),
        new DatanodeInfo[] {firstInfo});
    block.setStartOffset(0L);
    LocatedBlocks response = new LocatedBlocks(1024L, false,
        Arrays.asList(block), null, true, null, null);
    // The first block is learned when the file opens, before fetchBlockAt.
    Hdfs01ActorProbe.locatedBlocks(response, "/preadtest.dat");
    Hdfs01ActorProbe.readIo(other, 42L, "/preadtest.dat");
    try {
      Hdfs01ActorProbe.readIo(first, 42L, "/preadtest.dat");
      throw new AssertionError("first ordered fault was not injected");
    } catch (IOException expected) {
      if (expected instanceof EOFException) throw expected;
    }
    try {
      Hdfs01ActorProbe.readIo(first, 42L, "/preadtest.dat");
      throw new AssertionError("second ordered fault was not injected");
    } catch (EOFException expected) {
      // The second plan entry is reached only after the first has applied.
    }
    Hdfs01ActorProbe.targetCheck(response, 0L, "/preadtest.dat");
    System.out.println("actor probe smoke passed");
  }
}
