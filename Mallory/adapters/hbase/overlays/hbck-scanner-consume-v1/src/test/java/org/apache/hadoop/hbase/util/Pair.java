package org.apache.hadoop.hbase.util;

public final class Pair<A, B> {
  private final A first;
  public Pair(A first) { this.first = first; }
  public A getFirst() { return first; }
}
