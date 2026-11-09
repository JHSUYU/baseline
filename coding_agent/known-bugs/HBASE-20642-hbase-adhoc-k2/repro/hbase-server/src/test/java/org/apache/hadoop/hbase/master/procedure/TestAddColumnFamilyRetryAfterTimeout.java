/**
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
package org.apache.hadoop.hbase.master.procedure;

import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import java.io.IOException;
import java.util.Optional;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hbase.HBaseClassTestRule;
import org.apache.hadoop.hbase.HBaseTestingUtility;
import org.apache.hadoop.hbase.HConstants;
import org.apache.hadoop.hbase.InvalidFamilyOperationException;
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.client.Admin;
import org.apache.hadoop.hbase.client.ColumnFamilyDescriptorBuilder;
import org.apache.hadoop.hbase.client.Connection;
import org.apache.hadoop.hbase.client.ConnectionFactory;
import org.apache.hadoop.hbase.client.TableDescriptor;
import org.apache.hadoop.hbase.client.TableDescriptorBuilder;
import org.apache.hadoop.hbase.coprocessor.CoprocessorHost;
import org.apache.hadoop.hbase.coprocessor.MasterCoprocessor;
import org.apache.hadoop.hbase.coprocessor.MasterCoprocessorEnvironment;
import org.apache.hadoop.hbase.coprocessor.MasterObserver;
import org.apache.hadoop.hbase.coprocessor.ObserverContext;
import org.apache.hadoop.hbase.testclassification.LargeTests;
import org.apache.hadoop.hbase.testclassification.MasterTests;
import org.apache.hadoop.hbase.util.Bytes;
import org.junit.AfterClass;
import org.junit.BeforeClass;
import org.junit.ClassRule;
import org.junit.Test;
import org.junit.experimental.categories.Category;

/**
 * A client addColumnFamily() whose RPC response does not reach the client in time (slow master
 * handler after the ModifyTableProcedure has already been submitted) is retried by the client.
 * The retried request hits the "family already exists" check in HMaster.addColumn although the
 * family was added by this very same client operation, so the operation fails with
 * InvalidFamilyOperationException even though it succeeded.
 */
@Category({MasterTests.class, LargeTests.class})
public class TestAddColumnFamilyRetryAfterTimeout {

  @ClassRule
  public static final HBaseClassTestRule CLASS_RULE =
      HBaseClassTestRule.forClass(TestAddColumnFamilyRetryAfterTimeout.class);

  private static final HBaseTestingUtility TEST_UTIL = new HBaseTestingUtility();
  private static final TableName TABLE_NAME = TableName.valueOf("testAddColumnRetry");
  private static final byte[] FAMILY_0 = Bytes.toBytes("cf0");
  private static final byte[] FAMILY_1 = Bytes.toBytes("cf1");
  private static final int CLIENT_RPC_TIMEOUT_MS = 3000;

  /** Enabled only around the addColumnFamily call under test. */
  static final AtomicBoolean ARMED = new AtomicBoolean(false);
  static final AtomicInteger POST_MODIFY_CALLS = new AtomicInteger();
  static volatile CountDownLatch procedureCompleted = new CountDownLatch(1);

  /**
   * Models a slow master RPC handler: the first postModifyTable (which runs in the RPC handler
   * after the procedure was submitted) waits until the procedure has finished and then stalls
   * for longer than the client RPC timeout (e.g. GC pause / slow coprocessor / slow network).
   */
  public static class SlowMasterObserver implements MasterCoprocessor, MasterObserver {
    @Override
    public Optional<MasterObserver> getMasterObserver() {
      return Optional.of(this);
    }

    @Override
    public void postModifyTable(ObserverContext<MasterCoprocessorEnvironment> ctx,
        TableName tableName, TableDescriptor oldDescriptor, TableDescriptor currentDescriptor)
        throws IOException {
      if (!ARMED.get() || !TABLE_NAME.equals(tableName)) {
        return;
      }
      if (POST_MODIFY_CALLS.incrementAndGet() == 1) {
        try {
          procedureCompleted.await(60, TimeUnit.SECONDS);
          Thread.sleep(CLIENT_RPC_TIMEOUT_MS * 2L);
        } catch (InterruptedException e) {
          Thread.currentThread().interrupt();
        }
      }
    }

    @Override
    public void postCompletedModifyTableAction(ObserverContext<MasterCoprocessorEnvironment> ctx,
        TableName tableName, TableDescriptor oldDescriptor, TableDescriptor currentDescriptor)
        throws IOException {
      if (ARMED.get() && TABLE_NAME.equals(tableName)) {
        procedureCompleted.countDown();
      }
    }
  }

  @BeforeClass
  public static void beforeAllTests() throws Exception {
    TEST_UTIL.getConfiguration().set(CoprocessorHost.MASTER_COPROCESSOR_CONF_KEY,
      SlowMasterObserver.class.getName());
    TEST_UTIL.startMiniCluster(1);
  }

  @AfterClass
  public static void afterAllTests() throws Exception {
    TEST_UTIL.shutdownMiniCluster();
  }

  @Test
  public void testAddColumnRetriedAfterRpcTimeout() throws Exception {
    Admin admin = TEST_UTIL.getAdmin();
    admin.createTable(TableDescriptorBuilder.newBuilder(TABLE_NAME)
        .setColumnFamily(ColumnFamilyDescriptorBuilder.of(FAMILY_0)).build());
    admin.disableTable(TABLE_NAME);

    // A client with an ordinary (short-ish) rpc timeout and the default retry policy.
    Configuration clientConf = new Configuration(TEST_UTIL.getConfiguration());
    clientConf.setInt(HConstants.HBASE_RPC_TIMEOUT_KEY, CLIENT_RPC_TIMEOUT_MS);
    clientConf.setInt(HConstants.HBASE_CLIENT_RETRIES_NUMBER, 5);
    try (Connection conn = ConnectionFactory.createConnection(clientConf);
        Admin clientAdmin = conn.getAdmin()) {
      ARMED.set(true);
      try {
        clientAdmin.addColumnFamily(TABLE_NAME, ColumnFamilyDescriptorBuilder.of(FAMILY_1));
        fail("expected the retried addColumn to be rejected");
      } catch (InvalidFamilyOperationException e) {
        System.out.println("=== addColumnFamily (single client call) failed with: ===");
        e.printStackTrace(System.out);
        // The family was in fact added by this very operation.
        assertTrue(admin.getDescriptor(TABLE_NAME).hasColumnFamily(FAMILY_1));
        assertTrue(POST_MODIFY_CALLS.get() >= 1);
        // Surface the server-side frame of the check in the test failure.
        throw e;
      } finally {
        ARMED.set(false);
      }
    } finally {
      admin.deleteTable(TABLE_NAME);
    }
  }
}
