package org.apache.hadoop.hdfs.protocol.datatransfer.sasl;

import edu.uva.liftlab.graphchecker.contract.GapClass;
import edu.uva.liftlab.graphchecker.contract.GapKind;
import edu.uva.liftlab.graphchecker.runtime.MessageDoors;
import edu.uva.liftlab.graphchecker.runtime.RowRuntime;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import org.apache.hadoop.hdfs.protocol.proto.DataTransferProtos.DataTransferEncryptorMessageProto;
import org.apache.hadoop.thirdparty.protobuf.ByteString;
import org.apache.hadoop.thirdparty.protobuf.UnknownFieldSet;

/**
 * Exact same-JVM handoff for every HDFS data-transfer SASL protobuf leg.
 *
 * <p>The unknown field is a receipt token, not a guessed address or timing
 * join. The sender publishes GraphChecker context only after the delimited
 * protobuf has been written and flushed. The receiver waits for that exact
 * receipt before installing its causal scope. A peer in another JVM cannot
 * use this in-process rendezvous and is reported as a blocking gap.</p>
 */
public final class NativeHdfsSaslDoors {
  public static final String TRANSPORT = "HDFS_SASL";
  private static final int RECEIPT_FIELD = 50000;
  private static final int MAX_PENDING = 65536;
  private static final ConcurrentHashMap<String, CompletableFuture<MessageDoors.Outbound>>
      PENDING = new ConcurrentHashMap<>();
  private static final ThreadLocal<ClientExchange> CLIENT = new ThreadLocal<>();
  private static final ThreadLocal<ServerExchange> SERVER = new ThreadLocal<>();

  private NativeHdfsSaslDoors() { }

  /** Carries the submitting Balancer turn through its dispatcher executors. */
  public static Runnable carry(final Runnable task, final String api) {
    final Object scope = MessageDoors.captureScope();
    return new Runnable() {
      @Override public void run() {
        long token = MessageDoors.enterCarriedScope(scope, "CLIENT", api);
        if (token == 0L) {
          gap("SASL_ASYNC_SCOPE_UNPROVEN", api);
        }
        try { task.run(); }
        finally { MessageDoors.exitCarriedScope(token); }
      }
    };
  }

  /** Opens one client handshake, including all its request/response legs. */
  public static void beginClient(Object owner) {
    ClientExchange current = CLIENT.get();
    if (current != null) {
      current.depth++;
      return;
    }
    CLIENT.set(new ClientExchange("hdfs-sasl-" + UUID.randomUUID(), owner,
        MessageDoors.setAside()));
  }

  public static void beginServer(Object owner) {
    ServerExchange current = SERVER.get();
    if (current != null) {
      current.depth++;
      return;
    }
    SERVER.set(new ServerExchange(owner, MessageDoors.setAside()));
  }

  public static void endServer() {
    ServerExchange current = SERVER.get();
    if (current == null) {
      gap("SASL_SERVER_END_UNPAIRED", "no open handshake");
      return;
    }
    if (--current.depth > 0) return;
    SERVER.remove();
    MessageDoors.endInbound();
    MessageDoors.restore(current.serving);
  }

  public static void endClient() {
    ClientExchange current = CLIENT.get();
    if (current == null) {
      gap("SASL_CLIENT_END_UNPAIRED", "no open handshake");
      return;
    }
    if (--current.depth > 0) return;
    CLIENT.remove();
    MessageDoors.endInbound();
    MessageDoors.restore(current.serving);
  }

  /** Replaces each successful protobuf write in DataTransferSaslUtil. */
  public static void writeAndFlush(DataTransferEncryptorMessageProto original,
      OutputStream out) throws IOException {
    Leg leg = nextLeg();
    if (leg == null || PENDING.size() >= MAX_PENDING) {
      if (leg != null) gap("SASL_RECEIPTS_FULL", "receipt capacity reached");
      original.writeDelimitedTo(out);
      out.flush();
      return;
    }
    String receipt = UUID.randomUUID().toString();
    UnknownFieldSet.Field field = UnknownFieldSet.Field.newBuilder()
        .addLengthDelimited(ByteString.copyFromUtf8(receipt)).build();
    DataTransferEncryptorMessageProto message = original.toBuilder()
        .mergeUnknownFields(UnknownFieldSet.newBuilder()
            .addField(RECEIPT_FIELD, field).build()).build();
    CompletableFuture<MessageDoors.Outbound> handoff = new CompletableFuture<>();
    PENDING.put(receipt, handoff);
    try {
      message.writeDelimitedTo(out);
      out.flush();
      MessageDoors.Outbound sent = MessageDoors.outbound(TRANSPORT,
          leg.correlation, leg.attempt, leg.half, leg.owner, null, message);
      handoff.complete(sent);
      if (leg.client != null) leg.client.nextAttempt++;
    } catch (IOException | RuntimeException failure) {
      PENDING.remove(receipt, handoff);
      handoff.completeExceptionally(failure);
      throw failure;
    }
  }

  /** Replaces the one common parse used by client and server SASL readers. */
  public static DataTransferEncryptorMessageProto parse(InputStream in)
      throws IOException {
    DataTransferEncryptorMessageProto message =
        DataTransferEncryptorMessageProto.parseFrom(in);
    List<ByteString> values = message.getUnknownFields()
        .getField(RECEIPT_FIELD).getLengthDelimitedList();
    if (values.size() != 1) {
      gap("SASL_RECEIPT_MISSING_OR_AMBIGUOUS",
          "expected one transported receipt, observed " + values.size());
      return message;
    }
    String receipt = values.get(0).toStringUtf8();
    CompletableFuture<MessageDoors.Outbound> handoff = PENDING.get(receipt);
    if (handoff == null) {
      gap("SASL_RECEIPT_UNMATCHED", receipt);
      return message;
    }
    try {
      MessageDoors.Outbound sent = handoff.get(5, TimeUnit.SECONDS);
      if (sent == null || sent.trace.isEmpty()) {
        gap("SASL_SEND_UNATTRIBUTED", receipt);
      } else {
        Object owner = CLIENT.get() != null ? CLIENT.get().owner
            : SERVER.get() != null ? SERVER.get().owner : null;
        MessageDoors.inbound(sent.trace, sent.symbolic, TRANSPORT,
            sent.correlationId, sent.attemptId,
            CLIENT.get() == null ? MessageDoors.REQUEST : MessageDoors.RESPONSE,
            owner, true);
      }
    } catch (InterruptedException interrupted) {
      Thread.currentThread().interrupt();
      gap("SASL_RECEIPT_INTERRUPTED", receipt);
    } catch (ExecutionException | TimeoutException failure) {
      gap("SASL_RECEIPT_UNCONFIRMED", receipt + ": " + failure);
    } finally {
      PENDING.remove(receipt, handoff);
    }
    return message;
  }

  private static Leg nextLeg() {
    ClientExchange client = CLIENT.get();
    if (client != null) {
      MessageDoors.endInbound();
      return new Leg(client.correlation,
          Integer.toString(client.nextAttempt), MessageDoors.REQUEST,
          client.owner, client);
    }
    MessageDoors.Inbound received = MessageDoors.current();
    if (received != null && MessageDoors.REQUEST.equals(received.half)) {
      return new Leg(received.correlationId, received.attemptId,
          MessageDoors.RESPONSE,
          SERVER.get() == null ? null : SERVER.get().owner, null);
    }
    gap("SASL_SENDER_ROLE_UNPROVEN", "no client exchange or served request");
    return null;
  }

  private static void gap(String subject, String detail) {
    RowRuntime.gap(GapKind.MESSAGE_CONTEXT_REFUSED, GapClass.BLOCKING,
        subject, detail);
  }

  private static final class ClientExchange {
    final String correlation;
    final Object owner;
    final MessageDoors.Inbound serving;
    int nextAttempt = 1;
    int depth = 1;
    ClientExchange(String correlation, Object owner,
        MessageDoors.Inbound serving) {
      this.correlation = correlation;
      this.owner = owner;
      this.serving = serving;
    }
  }

  private static final class ServerExchange {
    final Object owner;
    final MessageDoors.Inbound serving;
    int depth = 1;
    ServerExchange(Object owner, MessageDoors.Inbound serving) {
      this.owner = owner;
      this.serving = serving;
    }
  }

  private static final class Leg {
    final String correlation;
    final String attempt;
    final String half;
    final Object owner;
    final ClientExchange client;
    Leg(String correlation, String attempt, String half, Object owner,
        ClientExchange client) {
      this.correlation = correlation;
      this.attempt = attempt;
      this.half = half;
      this.owner = owner;
      this.client = client;
    }
  }
}
