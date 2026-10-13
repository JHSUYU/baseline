package org.apache.hadoop.hbase;

import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Base64;
import java.util.List;
import org.apache.hadoop.hbase.client.Put;
import edu.uva.liftlab.mallory.graphchecker.runtime.MessageDoors;

/**
 * Observed table-state cell versions in hbase:meta. The writer hook runs only
 * after Table.put returns; the reader hook uses the Cell actually returned by
 * the Get. A repeated physical version remains ambiguous in MessageDoors.
 */
public final class GraphCheckerHBaseMetaState {
  private static final String STORE = "hbase-meta-table-state";

  private GraphCheckerHBaseMetaState() {
  }

  public static void writeAck(Put put) {
    if (put == null) {
      MessageDoors.gap("HBASE_META_STATE_WRITE_UNAVAILABLE", STORE, "null acknowledged Put");
      return;
    }
    try {
      int count = 0;
      Cell stateCell = null;
      for (List<Cell> cells : put.getFamilyCellMap().values()) {
        for (Cell cell : cells) {
          if (isStateCell(cell)) {
            stateCell = cell;
            count++;
          }
        }
      }
      if (count != 1) {
        MessageDoors.gap("HBASE_META_STATE_WRITE_UNAVAILABLE", STORE,
          "acknowledged Put contains " + count + " table-state cells");
        return;
      }
      MessageDoors.stored(STORE, version(stateCell), null);
    } catch (RuntimeException e) {
      MessageDoors.gap("HBASE_META_STATE_WRITE_UNAVAILABLE", STORE,
        "cannot inspect acknowledged Put: " + e.getClass().getName());
    }
  }

  public static void readCell(Cell cell) {
    try {
      if (!isStateCell(cell)) {
        MessageDoors.gap("HBASE_META_STATE_READ_UNAVAILABLE", STORE,
          "returned Cell is not a table-state cell");
        return;
      }
      MessageDoors.fetched(STORE, version(cell), null);
    } catch (RuntimeException e) {
      MessageDoors.gap("HBASE_META_STATE_READ_UNAVAILABLE", STORE,
        "cannot inspect returned Cell: " + e.getClass().getName());
    }
  }

  private static boolean isStateCell(Cell cell) {
    return cell != null && CellUtil.matchingFamily(cell, HConstants.TABLE_FAMILY)
      && CellUtil.matchingQualifier(cell, HConstants.TABLE_STATE_QUALIFIER);
  }

  static String version(Cell cell) {
    // HBase's physical Cell version is row/family/qualifier/timestamp/type.
    // The value digest checks that the two observations carry the same bytes;
    // it is not used as a substitute for the physical version coordinate.
    return "v1/" + encoded(CellUtil.cloneRow(cell)) + '/'
      + encoded(CellUtil.cloneFamily(cell)) + '/'
      + encoded(CellUtil.cloneQualifier(cell)) + '/'
      + cell.getTimestamp() + '/' + (cell.getTypeByte() & 0xff) + '/'
      + hex(sha256(CellUtil.cloneValue(cell)));
  }

  private static String encoded(byte[] value) {
    return Base64.getUrlEncoder().withoutPadding().encodeToString(value);
  }

  private static byte[] sha256(byte[] value) {
    try {
      return MessageDigest.getInstance("SHA-256").digest(value);
    } catch (NoSuchAlgorithmException e) {
      throw new IllegalStateException("SHA-256 unavailable", e);
    }
  }

  private static String hex(byte[] value) {
    char[] alphabet = "0123456789abcdef".toCharArray();
    char[] result = new char[value.length * 2];
    for (int i = 0; i < value.length; i++) {
      result[2 * i] = alphabet[(value[i] >>> 4) & 0xf];
      result[2 * i + 1] = alphabet[value[i] & 0xf];
    }
    return new String(result);
  }
}
