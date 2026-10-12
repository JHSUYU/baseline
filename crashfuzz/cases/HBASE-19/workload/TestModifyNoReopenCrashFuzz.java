/*
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements. See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership. The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License. You may obtain a copy of the License at
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

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.client.TableDescriptor;
import org.apache.hadoop.hbase.client.TableDescriptorBuilder;
import org.apache.hadoop.hbase.procedure2.ProcedureExecutor;
import org.apache.hadoop.hbase.procedure2.ProcedureTestingUtility;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

/**
 * The first no-reopen table modification from TestModifyTableProcedure.
 * The later region moves and Snappy change are unrelated to preflightChecks.
 */
public class TestModifyNoReopenCrashFuzz extends TestTableDDLProcedureBase {
  @BeforeAll
  public static void setupCluster() throws Exception {
    TestTableDDLProcedureBase.setupCluster();
  }

  @AfterAll
  public static void cleanupTest() throws Exception {
    TestTableDDLProcedureBase.cleanupTest();
  }

  @Test
  public void testModifyWithoutReopeningRegions() throws Exception {
    TableName tableName = TableName.valueOf("testModifyWithoutReopeningRegions");
    ProcedureExecutor<MasterProcedureEnv> procExec = getMasterProcedureExecutor();

    MasterProcedureTestingUtility.createTable(procExec, tableName, null, "cf");
    TableDescriptor original = UTIL.getAdmin().getDescriptor(tableName);
    TableDescriptor modified = TableDescriptorBuilder.newBuilder(original)
      .setValue("test.hbase.conf", "test.hbase.conf.value").build();
    long procId = ProcedureTestingUtility.submitAndWait(procExec,
      new ModifyTableProcedure(procExec.getEnvironment(), modified, null, original, false, false));
    ProcedureTestingUtility.assertProcNotFailed(procExec.getResult(procId));
    assertEquals("test.hbase.conf.value",
      UTIL.getAdmin().getDescriptor(tableName).getValue("test.hbase.conf"));
  }
}
