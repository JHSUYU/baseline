package edu.uva.liftlab.mallory.graphchecker.weave.fixture;

/** The integer selected before parseInt remains live in its catch body. */
public final class FixtureCatchLiveInt {
    public int parse(String raw) {
        String[] parts = {raw, "one"};
        int position = 0;
        try {
            return Integer.parseInt(parts[position++]);
        } catch (NumberFormatException ignored) {
            StringBuilder message = new StringBuilder();
            message.append(parts[position - 1]);
            return message.toString().length();
        }
    }
}
