package org.apache.zookeeper.data;

public final class Stat {
  private final String path;
  public Stat(String path) { this.path = path; }
  public String getPath() { return path; }
}
