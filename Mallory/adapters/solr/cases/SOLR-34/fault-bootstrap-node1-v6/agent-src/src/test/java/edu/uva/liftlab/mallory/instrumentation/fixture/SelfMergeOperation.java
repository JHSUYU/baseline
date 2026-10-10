package edu.uva.liftlab.mallory.instrumentation.fixture;

import java.util.ArrayList;

/** Forces ASM to merge a frame containing the class currently being transformed. */
public class SelfMergeOperation {
  public Object choose(boolean self) {
    Object selected;
    if (self) selected = this;
    else selected = new ArrayList<String>();
    return selected;
  }

  public Object[] chooseArray(boolean strings) {
    Object[] selected;
    if (strings) selected = new String[1];
    else selected = new Integer[1];
    return selected;
  }
}
