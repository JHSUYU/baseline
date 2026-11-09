/*
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package org.apache.hadoop.hbase.util;

import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

import java.io.IOException;
import java.util.Collections;
import java.util.List;
import org.apache.hadoop.hbase.HBaseTestingUtil;
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.client.Hbck;
import org.apache.hadoop.hbase.client.RegionInfo;
import org.apache.hadoop.hbase.client.RegionInfoBuilder;
import org.apache.hadoop.hbase.client.Result;
import org.apache.hadoop.hbase.client.ResultScanner;
import org.apache.hadoop.hbase.client.Scan;
import org.apache.hadoop.hbase.client.Table;
import org.apache.hadoop.hbase.master.RegionState;
import org.apache.hadoop.hbase.testclassification.MediumTests;
import org.apache.hadoop.hbase.util.hbck.HbckTestingUtil;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * An operator uses the HBCK2 "setRegionState" admin API (Hbck#setRegionStateInMeta) on the
 * hbase:meta region. The master writes the hbase:meta region's state as a row into hbase:meta
 * itself (the meta region's state is supposed to live only in the master local region), and a
 * later run of HBaseFsck aborts in loadMetaEntries with "Two entries in hbase:meta are same".
 */
@Tag(MediumTests.TAG)
public class TestHBaseFsckMetaRowInMeta {

  private static final Logger LOG = LoggerFactory.getLogger(TestHBaseFsckMetaRowInMeta.class);

  private static final HBaseTestingUtil UTIL = new HBaseTestingUtil();

  @BeforeEach
  public void setUp() throws Exception {
    UTIL.getConfiguration().setBoolean("hbase.write.hbck1.lock.file", false);
    UTIL.startMiniCluster(1);
    UTIL.createTable(TableName.valueOf("t"), "f");
  }

  @AfterEach
  public void tearDown() throws Exception {
    UTIL.shutdownMiniCluster();
  }

  @Test
  public void test() throws Exception {
    // a healthy cluster: hbck passes
    HbckTestingUtil.assertNoErrors(HbckTestingUtil.doFsck(UTIL.getConfiguration(), false));

    // operator sets the state of the hbase:meta region through the HBCK2 API
    String metaEncoded = RegionInfoBuilder.FIRST_META_REGIONINFO.getEncodedName();
    try (Hbck hbck = UTIL.getHbck()) {
      LOG.info("previous states {}", hbck.setRegionStateInMeta(
        Collections.singletonMap(metaEncoded, RegionState.State.CLOSED)));
    }

    // the hbase:meta region now has its own row inside hbase:meta
    boolean metaRowFound = false;
    try (Table t = UTIL.getConnection().getTable(TableName.META_TABLE_NAME);
      ResultScanner rs = t.getScanner(new Scan())) {
      for (Result r : rs) {
        RegionInfo ri = org.apache.hadoop.hbase.CatalogFamilyFormat.getRegionInfo(r);
        LOG.info("meta row {} -> {}", org.apache.hadoop.hbase.util.Bytes.toStringBinary(r.getRow()),
          ri);
        if (ri != null && ri.isMetaRegion()) {
          metaRowFound = true;
        }
      }
    }
    assertTrue(metaRowFound, "expected bogus hbase:meta row for the meta region");

    try {
      HbckTestingUtil.doFsck(UTIL.getConfiguration(), false);
      fail("hbck should have failed");
    } catch (IOException e) {
      LOG.error("HBaseFsck failed", e);
      e.printStackTrace();
      assertNotNull(e.getMessage());
      assertTrue(e.getMessage().contains("Two entries in hbase:meta are same"), e.getMessage());
      boolean frame = false;
      for (StackTraceElement el : e.getStackTrace()) {
        if (el.getClassName().startsWith(HBaseFsck.class.getName())
          && "HBaseFsck.java".equals(el.getFileName()) && el.getLineNumber() == 2742) {
          frame = true;
        }
      }
      assertTrue(frame, "expected frame HBaseFsck.java:2742");
      throw e;
    }
  }
}
