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
package org.apache.hadoop.hbase.namespace;

import java.util.concurrent.Future;
import org.apache.hadoop.hbase.HBaseTestingUtil;
import org.apache.hadoop.hbase.NamespaceDescriptor;
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.client.Admin;
import org.apache.hadoop.hbase.client.ColumnFamilyDescriptorBuilder;
import org.apache.hadoop.hbase.client.TableDescriptor;
import org.apache.hadoop.hbase.client.TableDescriptorBuilder;
import org.apache.hadoop.hbase.master.TableNamespaceManager;
import org.apache.hadoop.hbase.quotas.QuotaUtil;
import org.apache.hadoop.hbase.testclassification.MediumTests;
import org.apache.hadoop.hbase.util.Bytes;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;

/**
 * Namespace quotas on a one-region-server cluster. A namespace allows two regions. Its first table
 * is created with two regions, disabled, truncated without its splits and disabled again; it is
 * then deleted asynchronously, and two seconds later a one-region table is created in the same
 * namespace. The test waits for the deletion to finish.
 */
@Tag(MediumTests.TAG)
public class TestAdhocWorkload22 {
  private static final HBaseTestingUtil UTIL = new HBaseTestingUtil();
  private static final String NAMESPACE = "adhoc_workload_22";

  @BeforeAll
  public static void setUp() throws Exception {
    UTIL.getConfiguration().setBoolean(QuotaUtil.QUOTA_CONF_KEY, true);
    UTIL.startMiniCluster(1);
    UTIL.waitFor(30000,
      () -> UTIL.getMiniHBaseCluster().getMaster().getMasterQuotaManager().isQuotaInitialized());
  }

  @AfterAll
  public static void tearDown() throws Exception {
    UTIL.shutdownMiniCluster();
  }

  @Test
  public void run() throws Exception {
    Admin admin = UTIL.getAdmin();
    admin.createNamespace(NamespaceDescriptor.create(NAMESPACE)
      .addConfiguration(TableNamespaceManager.KEY_MAX_REGIONS, "2").build());
    TableName truncated = TableName.valueOf(NAMESPACE, "truncated");
    admin.createTable(table(truncated), new byte[][] { Bytes.toBytes("m") });
    admin.disableTable(truncated);
    admin.truncateTable(truncated, false);
    admin.disableTable(truncated);

    Future<Void> deletion = admin.deleteTableAsync(truncated);
    Thread.sleep(2000);
    admin.createTable(table(TableName.valueOf(NAMESPACE, "created")));
    deletion.get();
  }

  private static TableDescriptor table(TableName name) {
    return TableDescriptorBuilder.newBuilder(name)
      .setColumnFamily(ColumnFamilyDescriptorBuilder.of("f")).build();
  }
}
