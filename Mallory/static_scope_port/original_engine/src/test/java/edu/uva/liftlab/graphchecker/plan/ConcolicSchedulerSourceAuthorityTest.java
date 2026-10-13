package edu.uva.liftlab.graphchecker.plan;

import com.google.gson.JsonObject;
import org.junit.Test;

import java.io.IOException;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

public final class ConcolicSchedulerSourceAuthorityTest {
    // Exact declaration shape from the ZK07 original healthy Recorder catalog.
    private static JsonObject declaration(String authority) {
        JsonObject row = new JsonObject();
        row.addProperty("schemaVersion", 1);
        row.addProperty("kind", "STATIC_SYMBOLIC_SOURCE_DECLARATION");
        row.addProperty("authority", authority);
        row.addProperty("sourceId", "CONFIG:zookeeper.db.autocreate");
        row.addProperty("fieldSignature",
                "<org.apache.zookeeper.server.persistence.FileTxnSnapLog: boolean autoCreateDB>");
        row.addProperty("declarationMethod",
                "<org.apache.zookeeper.server.persistence.FileTxnSnapLog: long restore(org.apache.zookeeper.server.DataTree,java.util.Map,org.apache.zookeeper.server.persistence.FileTxnSnapLog$PlayBackListener)>");
        row.addProperty("declarationUnitIndex", 26);
        return row;
    }

    private static Method mintMethod() throws Exception {
        Class<?> selection = Class.forName(
                "edu.uva.liftlab.graphchecker.plan.ConcolicScheduler$SymbolicInputSelection");
        Method method = selection.getDeclaredMethod("declareMintSite",
                Map.class, JsonObject.class);
        method.setAccessible(true);
        return method;
    }

    @Test
    public void acceptsBothDeclaredAuthoritiesAndRejectsUnknown() throws Exception {
        Method mint = mintMethod();
        Map<String, String> sites = new LinkedHashMap<>();
        JsonObject config = declaration(
                StaticSymbolicSourceDeclaration.CONFIG_AUTHORITY);
        assertEquals(1, edu.uva.liftlab.graphchecker.smt.JsonFields.exactInteger(
                config, "schemaVersion", -1));
        assertEquals(StaticSymbolicSourceDeclaration.KIND,
                config.get("kind").getAsString());
        assertTrue(StaticSymbolicSourceDeclaration.authority(
                config.get("authority").getAsString()));
        mint.invoke(null, sites, config);
        assertEquals(config.get("fieldSignature").getAsString(),
                sites.get("CONFIG:zookeeper.db.autocreate"));

        JsonObject explicit = declaration(
                StaticSymbolicSourceDeclaration.AUTHORITY);
        explicit.addProperty("sourceId", "HOOK:config");
        mint.invoke(null, sites, explicit);
        assertEquals(2, sites.size());

        try {
            mint.invoke(null, sites, declaration("UNRECOGNIZED_AUTHORITY"));
            fail("unknown source authority must be refused");
        } catch (InvocationTargetException expected) {
            if (!(expected.getCause() instanceof IOException)) {
                throw expected;
            }
            assertEquals("malformed static symbolic source declaration",
                    expected.getCause().getMessage());
        }
        assertEquals(2, sites.size());
    }
}
