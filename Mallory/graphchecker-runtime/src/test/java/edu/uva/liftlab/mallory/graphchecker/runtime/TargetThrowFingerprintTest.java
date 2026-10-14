package edu.uva.liftlab.mallory.graphchecker.runtime;

import com.google.gson.JsonObject;
import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class TargetThrowFingerprintTest {
    @Test public void keepsOnlyBoundedStructuralAndNumericEvidence() {
        String secret = "private-payload-never-copy-this";
        String message = "Missing block key (keyID=41). Current key: 46 "
                + secret + new String(new char[600]).replace('\0', 'x');
        JsonObject first = TargetThrowFingerprint.fields("check", null, null,
                new IllegalStateException(message));
        JsonObject second = TargetThrowFingerprint.fields("check", null, null,
                new IllegalStateException(message.replace("keyID=41", "keyID=42")));
        assertEquals(1, first.get("fingerprintVersion").getAsInt());
        assertEquals("41", first.getAsJsonObject("numericAttributes")
                .get("keyid").getAsString());
        assertEquals("46", first.getAsJsonObject("numericAttributes")
                .get("current_key").getAsString());
        assertEquals(first.get("structuralFingerprint"),
                second.get("structuralFingerprint"));
        assertFalse(first.get("messagePrefixSha256").equals(
                second.get("messagePrefixSha256")));
        assertTrue(first.get("messageTruncated").getAsBoolean());
        assertTrue(first.getAsJsonArray("stackMethods").size() <= 16);
        assertFalse(first.toString().contains(secret));
        assertFalse(first.toString().contains("Missing block key"));
    }
}
