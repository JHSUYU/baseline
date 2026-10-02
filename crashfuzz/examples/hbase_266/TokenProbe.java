import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hbase.HBaseConfiguration;
import org.apache.hadoop.hbase.client.Connection;
import org.apache.hadoop.hbase.client.ConnectionFactory;
import org.apache.hadoop.hbase.security.token.TokenUtil;
import org.apache.hadoop.security.token.Token;

/** Diagnostic for the allKeys.get(keyId) token-authentication target. */
public final class TokenProbe {
    public static void main(String[] args) throws Exception {
        Configuration config = HBaseConfiguration.create();
        try (Connection connection = ConnectionFactory.createConnection(config)) {
            Token<?> token = TokenUtil.obtainToken(connection);
            if (token == null) throw new IllegalStateException("no token returned");
            System.out.println("delegation token obtained; kind=" + token.getKind());
        }
    }
}
