package edu.uva.liftlab.mallory.graphchecker.contract;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/** The GraphChecker contract's SHA-256 ID spelling, local to Mallory. */
public final class Digest {
    private static final char[] HEX = "0123456789abcdef".toCharArray();

    private Digest() { }

    public static String digest(String value, int length) {
        return hex((value == null ? "" : value).getBytes(StandardCharsets.UTF_8), length);
    }

    /** Full SHA-256 for a transported value, without decoding binary payloads. */
    public static String payload(byte[] value) {
        if (value == null) throw new IllegalArgumentException("payload is null");
        return hex(value, 0);
    }

    private static String hex(byte[] value, int length) {
        byte[] hash;
        try {
            hash = MessageDigest.getInstance("SHA-256").digest(value);
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
        char[] encoded = new char[hash.length * 2];
        for (int index = 0; index < hash.length; index++) {
            int octet = hash[index] & 0xff;
            encoded[index * 2] = HEX[octet >>> 4];
            encoded[index * 2 + 1] = HEX[octet & 0x0f];
        }
        String full = new String(encoded);
        return length <= 0 || length >= full.length()
                ? full : full.substring(0, length);
    }
}
