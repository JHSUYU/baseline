package edu.uva.liftlab.graphchecker.causynth;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import org.junit.Test;

import java.util.LinkedHashSet;
import java.util.Set;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

/** Observed sites must be numbered before any concolic body rewrite. */
public final class ObservedSitePretagEnvelopeTest {
    @Test public void fieldStoreOwnerEntersPreTagEnvelopeWithoutOtherActions()
            throws Exception {
        String method = "<example.ConnectionListener: void operationComplete()>";
        JsonObject store = new JsonObject();
        store.addProperty("method", method);
        store.addProperty("unitIndex", 48);
        store.addProperty("siteId", method + "#u48");
        store.addProperty("cell", "<example.Connection: boolean initialized>");
        store.addProperty("declaredCallee", "");
        store.addProperty("read", false);
        store.addProperty("field", true);
        store.addProperty("container", false);
        JsonArray observed = new JsonArray();
        observed.add(store);

        ConcolicInstrumentationSelections.ConcolicMaterializationSelection selection =
                new ConcolicInstrumentationSelections.ConcolicMaterializationSelection();
        selection.addObservedSites(observed);
        Set<String> envelope = new LinkedHashSet<>();
        ConcolicInstrumentationSelections.InstrumentationPlan
                .addMaterializationMethods(envelope, selection);

        assertEquals(1, envelope.size());
        assertTrue(envelope.contains(method));
    }
}
