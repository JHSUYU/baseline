package edu.uva.liftlab.graphchecker.runtime;

import org.junit.Test;

import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

/** Protects WIRE_FLOW value transport while the later CODEC_PORT is absent. */
public class MessageDoorsPayloadCompatibilityTest {
    @Test public void serializedPayloadScopeIsExactNestedAndRestored() {
        byte[] first = "first".getBytes(StandardCharsets.UTF_8);
        byte[] second = "second".getBytes(StandardCharsets.UTF_8);
        assertEquals("", MessageDoors.currentMessagePayloadKey());
        String outer;
        try (MessageDoors.MessagePayloadScope ignored =
                     MessageDoors.beginMessagePayload("ZOOKEEPER", "/queue", first)) {
            outer = MessageDoors.currentMessagePayloadKey();
            assertEquals(64, outer.length());
            try (MessageDoors.MessagePayloadScope nested =
                         MessageDoors.beginMessagePayload("ZOOKEEPER", "/queue", second)) {
                assertFalse(outer.equals(MessageDoors.currentMessagePayloadKey()));
            }
            assertEquals(outer, MessageDoors.currentMessagePayloadKey());
        }
        assertEquals("", MessageDoors.currentMessagePayloadKey());
        try (MessageDoors.MessagePayloadScope ignored =
                     MessageDoors.beginMessagePayload("ZOOKEEPER", "/queue", first)) {
            assertEquals(outer, MessageDoors.currentMessagePayloadKey());
        }
        try (MessageDoors.MessagePayloadScope ignored =
                     MessageDoors.beginMessagePayload("ZOOKEEPER", "/other", first)) {
            assertFalse(outer.equals(MessageDoors.currentMessagePayloadKey()));
        }
        try (MessageDoors.MessagePayloadScope ignored =
                     MessageDoors.beginMessagePayload("ZOOKEEPER", "/queue", null)) {
            assertEquals("", MessageDoors.currentMessagePayloadKey());
        }
    }

    @Test public void payloadOverloadCarriesTheExactStagedPortElement()
            throws Exception {
        String prior = System.getProperty("causynth.wire.declarations");
        System.clearProperty("causynth.wire.declarations");
        SymbolicMessageEnvelope.clear();
        MessageDoors.Inbound inbound = null;
        try {
            assertTrue(SymbolicMessageEnvelope.stage("block-key-id", 1729L,
                    null));
            MessageDoors.Outbound message = MessageDoors.outbound("HDFS_RPC",
                    "client-7:call-3", "retry-0", MessageDoors.REQUEST,
                    null, null, new Object());
            assertEquals("client-7:call-3", message.correlationId);
            assertEquals("retry-0", message.attemptId);
            assertTrue(message.symbolic.startsWith("CSE5;"));
            inbound = MessageDoors.inbound("", message.symbolic,
                    "HDFS_RPC", message.correlationId, message.attemptId,
                    MessageDoors.REQUEST, null, false);
            assertEquals(1729L, SymbolicMessageEnvelope.take("block-key-id"));
            assertEquals(SymbolicMessageEnvelope.ABSENT,
                    SymbolicMessageEnvelope.take("other-port"));
        } finally {
            MessageDoors.endInbound(inbound);
            SymbolicMessageEnvelope.clear();
            if (prior == null) System.clearProperty(
                    "causynth.wire.declarations");
            else System.setProperty("causynth.wire.declarations", prior);
        }
    }

    @Test public void codecDeclarationsAreRecognizedAsUnsupported()
            throws Exception {
        Path rows = Files.createTempFile("mallory-wire-declarations-", ".jsonl");
        Files.write(rows, ("{\"kind\":\"CODEC\",\"codec\":\"PROTO\"}\n"
                + "{\"kind\":\"TRANSPORT\",\"transport\":\"HDFS_RPC\","
                + "\"request\":\"PROTO\"}\n").getBytes(StandardCharsets.UTF_8));
        String prior = System.getProperty("causynth.wire.declarations");
        System.setProperty("causynth.wire.declarations", rows.toString());
        try {
            Method requested = MessageDoors.class.getDeclaredMethod(
                    "codecRequested", String.class, String.class);
            requested.setAccessible(true);
            assertTrue((Boolean) requested.invoke(null, "HDFS_RPC",
                    MessageDoors.REQUEST));
            assertFalse((Boolean) requested.invoke(null, "HDFS_RPC",
                    MessageDoors.RESPONSE));
            assertFalse((Boolean) requested.invoke(null, "OTHER_RPC",
                    MessageDoors.REQUEST));
        } finally {
            if (prior == null) System.clearProperty(
                    "causynth.wire.declarations");
            else System.setProperty("causynth.wire.declarations", prior);
        }
    }
}
