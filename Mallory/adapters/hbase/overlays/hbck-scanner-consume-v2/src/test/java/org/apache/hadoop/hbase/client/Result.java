package org.apache.hadoop.hbase.client;

public final class Result {
  private final int value;
  public Result(int value) { this.value = value; }
  @Override public boolean equals(Object other) {
    return other instanceof Result && value == ((Result) other).value;
  }
  @Override public int hashCode() { return value; }
}
