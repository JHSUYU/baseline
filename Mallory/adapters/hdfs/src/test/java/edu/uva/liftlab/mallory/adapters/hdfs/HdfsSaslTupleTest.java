package edu.uva.liftlab.mallory.adapters.hdfs;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import org.junit.Test;

public class HdfsSaslTupleTest {
  public static final class PeerEndpoints {
    private final Socket socket;
    PeerEndpoints(Socket socket) { this.socket = socket; }
    public String getLocalAddressString() {
      return socket.getLocalSocketAddress().toString();
    }
    public String getRemoteAddressString() {
      return socket.getRemoteSocketAddress().toString();
    }
  }

  public static final class DomainEndpoints {
    public String getLocalAddressString() { return "<local>"; }
    public String getRemoteAddressString() { return "unix:/tmp/dn.sock"; }
  }

  @Test public void sameConnectionMatchesFromBothTcpEnds() throws Exception {
    InetAddress loopback = InetAddress.getByName("127.0.0.1");
    try (ServerSocket listener = new ServerSocket(0, 1, loopback);
         Socket client = new Socket(loopback, listener.getLocalPort());
         Socket server = listener.accept()) {
      String tuple = HdfsHooks.clientTuple(client);
      assertTrue(tuple.startsWith("127.0.0.1:"));
      assertEquals(tuple, HdfsHooks.clientTuple(new PeerEndpoints(client)));
      assertEquals(tuple, HdfsHooks.serverTuple(new PeerEndpoints(server)));
    }
  }

  @Test public void unixEndpointsDoNotCreateAnExactMatch() {
    assertNull(HdfsHooks.clientTuple(new DomainEndpoints()));
    assertNull(HdfsHooks.serverTuple(new DomainEndpoints()));
  }
}
