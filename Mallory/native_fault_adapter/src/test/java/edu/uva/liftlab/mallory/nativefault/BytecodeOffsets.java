package edu.uva.liftlab.mallory.nativefault;

import java.io.ByteArrayInputStream;
import java.io.DataInputStream;
import java.io.IOException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Original classfile instruction BCIs, independent of ASM's tree indices. */
final class BytecodeOffsets {
    private BytecodeOffsets() { }

    static Map<String, List<Integer>> instructions(byte[] classfile) throws IOException {
        DataInputStream in = new DataInputStream(new ByteArrayInputStream(classfile));
        if (in.readInt() != 0xCAFEBABE) throw new IOException("not a classfile");
        in.readUnsignedShort();
        in.readUnsignedShort();
        String[] utf8 = new String[in.readUnsignedShort()];
        for (int i = 1; i < utf8.length; i++) {
            int tag = in.readUnsignedByte();
            switch (tag) {
                case 1: utf8[i] = in.readUTF(); break;
                case 3: case 4: in.skipBytes(4); break;
                case 5: case 6: in.skipBytes(8); i++; break;
                case 7: case 8: case 16: case 19: case 20: in.skipBytes(2); break;
                case 9: case 10: case 11: case 12: case 17: case 18:
                    in.skipBytes(4); break;
                case 15: in.skipBytes(3); break;
                default: throw new IOException("unknown classfile constant " + tag);
            }
        }
        in.skipBytes(6); // access, this, super
        int interfaces = in.readUnsignedShort();
        in.skipBytes(interfaces * 2);
        skipMembers(in, in.readUnsignedShort()); // fields
        Map<String, List<Integer>> result = new HashMap<>();
        int methods = in.readUnsignedShort();
        for (int i = 0; i < methods; i++) {
            in.readUnsignedShort();
            String name = utf8[in.readUnsignedShort()];
            String descriptor = utf8[in.readUnsignedShort()];
            int attributes = in.readUnsignedShort();
            for (int j = 0; j < attributes; j++) {
                String attribute = utf8[in.readUnsignedShort()];
                int length = in.readInt();
                byte[] value = new byte[length];
                in.readFully(value);
                if ("Code".equals(attribute)) {
                    DataInputStream code = new DataInputStream(
                            new ByteArrayInputStream(value));
                    code.skipBytes(4); // max_stack, max_locals
                    byte[] bytes = new byte[code.readInt()];
                    code.readFully(bytes);
                    result.put(name + '\n' + descriptor, walk(bytes));
                }
            }
        }
        return result;
    }

    private static void skipMembers(DataInputStream in, int count) throws IOException {
        for (int i = 0; i < count; i++) {
            in.skipBytes(6);
            int attributes = in.readUnsignedShort();
            for (int j = 0; j < attributes; j++) {
                in.skipBytes(2);
                int length = in.readInt();
                while (length > 0) {
                    int skipped = in.skipBytes(length);
                    if (skipped <= 0) throw new IOException("truncated field attribute");
                    length -= skipped;
                }
            }
        }
    }

    private static List<Integer> walk(byte[] bytes) throws IOException {
        List<Integer> instructions = new ArrayList<>();
        for (int bci = 0; bci < bytes.length;) {
            int opcode = bytes[bci] & 0xff;
            instructions.add(bci);
            int size = size(bytes, bci, opcode);
            if (size <= 0 || bci + size > bytes.length) {
                throw new IOException("invalid instruction at bytecode offset " + bci);
            }
            bci += size;
        }
        return instructions;
    }

    private static int size(byte[] bytes, int bci, int op) throws IOException {
        if (op == 170 || op == 171) {
            int aligned = (bci + 4) & ~3;
            if (aligned + 8 > bytes.length) throw new IOException("truncated switch");
            if (op == 170) {
                int low = word(bytes, aligned + 4);
                int high = word(bytes, aligned + 8);
                long size = (long) aligned - bci + 12L + 4L * (high - low + 1L);
                if (size <= 0 || size > Integer.MAX_VALUE) throw new IOException("invalid tableswitch");
                return (int) size;
            }
            int pairs = word(bytes, aligned + 4);
            long size = (long) aligned - bci + 8L + 8L * pairs;
            if (size <= 0 || size > Integer.MAX_VALUE) throw new IOException("invalid lookupswitch");
            return (int) size;
        }
        if (op == 196) {
            if (bci + 1 >= bytes.length) throw new IOException("truncated wide");
            return (bytes[bci + 1] & 0xff) == 132 ? 6 : 4;
        }
        if (op == 185 || op == 186 || op == 200 || op == 201) return 5;
        if (op == 197) return 4;
        if (op == 17 || op == 19 || op == 20 || op == 132
                || op >= 153 && op <= 168 || op == 198 || op == 199
                || op >= 178 && op <= 184 || op == 187 || op == 189
                || op == 192 || op == 193) return 3;
        if (op == 16 || op == 18 || op == 188 || op == 169
                || op >= 21 && op <= 25 || op >= 54 && op <= 58) return 2;
        if (op > 201) throw new IOException("invalid opcode " + op);
        return 1;
    }

    private static int word(byte[] bytes, int start) throws IOException {
        if (start + 4 > bytes.length) throw new IOException("truncated switch word");
        return (bytes[start] & 0xff) << 24 | (bytes[start + 1] & 0xff) << 16
                | (bytes[start + 2] & 0xff) << 8 | bytes[start + 3] & 0xff;
    }
}
