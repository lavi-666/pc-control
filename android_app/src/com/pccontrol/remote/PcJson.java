package com.pccontrol.remote;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Small, dependency-free JSON reader/writer (pure Java, so the API layer is testable on a desktop
 * JVM where org.json is not available). Objects become {@link LinkedHashMap}, arrays {@link ArrayList},
 * numbers {@link Long} (integers) or {@link Double}, plus String / Boolean / null.
 */
public final class PcJson {
    private PcJson() {}

    // ------------------------------------------------------------------ parsing
    public static Object parse(String s) {
        if (s == null) throw new IllegalArgumentException("null JSON");
        Parser p = new Parser(s);
        p.ws();
        Object v = p.value(0);
        p.ws();
        if (p.i != s.length()) throw p.err("trailing characters");
        return v;
    }

    /** Parses and wraps an object; returns an empty object for anything that is not a JSON object. */
    public static O parseObj(String s) {
        try {
            Object v = parse(s);
            if (v instanceof Map) return new O(cast(v));
        } catch (RuntimeException ignored) {
        }
        return new O(null);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> cast(Object v) {
        return (Map<String, Object>) v;
    }

    private static final class Parser {
        final String s;
        int i;

        Parser(String s) {
            this.s = s;
        }

        IllegalArgumentException err(String m) {
            return new IllegalArgumentException("JSON: " + m + " at " + i);
        }

        void ws() {
            while (i < s.length()) {
                char c = s.charAt(i);
                if (c == ' ' || c == '\n' || c == '\r' || c == '\t') i++;
                else break;
            }
        }

        Object value(int depth) {
            if (depth > 64) throw err("too deep");
            if (i >= s.length()) throw err("unexpected end");
            char c = s.charAt(i);
            switch (c) {
                case '{': return object(depth);
                case '[': return array(depth);
                case '"': return string();
                case 't': lit("true"); return Boolean.TRUE;
                case 'f': lit("false"); return Boolean.FALSE;
                case 'n': lit("null"); return null;
                default:
                    if (c == '-' || (c >= '0' && c <= '9')) return number();
                    throw err("unexpected '" + c + "'");
            }
        }

        void lit(String w) {
            if (!s.startsWith(w, i)) throw err("expected " + w);
            i += w.length();
        }

        Map<String, Object> object(int depth) {
            Map<String, Object> m = new LinkedHashMap<>();
            i++;
            ws();
            if (i < s.length() && s.charAt(i) == '}') { i++; return m; }
            while (true) {
                ws();
                if (i >= s.length() || s.charAt(i) != '"') throw err("expected key");
                String k = string();
                ws();
                if (i >= s.length() || s.charAt(i) != ':') throw err("expected ':'");
                i++;
                ws();
                m.put(k, value(depth + 1));
                ws();
                if (i >= s.length()) throw err("unterminated object");
                char c = s.charAt(i++);
                if (c == '}') return m;
                if (c != ',') throw err("expected ',' or '}'");
            }
        }

        List<Object> array(int depth) {
            List<Object> a = new ArrayList<>();
            i++;
            ws();
            if (i < s.length() && s.charAt(i) == ']') { i++; return a; }
            while (true) {
                ws();
                a.add(value(depth + 1));
                ws();
                if (i >= s.length()) throw err("unterminated array");
                char c = s.charAt(i++);
                if (c == ']') return a;
                if (c != ',') throw err("expected ',' or ']'");
            }
        }

        String string() {
            i++; // opening quote
            StringBuilder sb = new StringBuilder();
            while (true) {
                if (i >= s.length()) throw err("unterminated string");
                char c = s.charAt(i++);
                if (c == '"') return sb.toString();
                if (c != '\\') { sb.append(c); continue; }
                if (i >= s.length()) throw err("bad escape");
                char e = s.charAt(i++);
                switch (e) {
                    case '"': sb.append('"'); break;
                    case '\\': sb.append('\\'); break;
                    case '/': sb.append('/'); break;
                    case 'b': sb.append('\b'); break;
                    case 'f': sb.append('\f'); break;
                    case 'n': sb.append('\n'); break;
                    case 'r': sb.append('\r'); break;
                    case 't': sb.append('\t'); break;
                    case 'u':
                        if (i + 4 > s.length()) throw err("bad unicode escape");
                        try {
                            sb.append((char) Integer.parseInt(s.substring(i, i + 4), 16));
                        } catch (NumberFormatException ex) {
                            throw err("bad unicode escape");
                        }
                        i += 4;
                        break;
                    default: throw err("bad escape \\" + e);
                }
            }
        }

        Object number() {
            int st = i;
            if (s.charAt(i) == '-') i++;
            boolean frac = false;
            while (i < s.length()) {
                char c = s.charAt(i);
                if (c >= '0' && c <= '9') i++;
                else if (c == '.' || c == 'e' || c == 'E' || c == '+' || c == '-') { frac = true; i++; }
                else break;
            }
            String n = s.substring(st, i);
            try {
                if (!frac) {
                    if (n.length() < 19) return Long.parseLong(n);
                    return Double.parseDouble(n);
                }
                return Double.parseDouble(n);
            } catch (NumberFormatException e) {
                throw err("bad number " + n);
            }
        }
    }

    // ------------------------------------------------------------------ writing
    public static String stringify(Object v) {
        StringBuilder sb = new StringBuilder();
        write(sb, v);
        return sb.toString();
    }

    @SuppressWarnings("unchecked")
    private static void write(StringBuilder sb, Object v) {
        if (v == null) {
            sb.append("null");
        } else if (v instanceof O) {
            write(sb, ((O) v).map);
        } else if (v instanceof String) {
            quote(sb, (String) v);
        } else if (v instanceof Boolean) {
            sb.append(v.toString());
        } else if (v instanceof Double || v instanceof Float) {
            double d = ((Number) v).doubleValue();
            if (Double.isNaN(d) || Double.isInfinite(d)) sb.append("null");
            else if (d == Math.rint(d) && Math.abs(d) < 1e15) sb.append((long) d);
            else sb.append(d);
        } else if (v instanceof Number) {
            sb.append(((Number) v).longValue());
        } else if (v instanceof Map) {
            sb.append('{');
            boolean first = true;
            for (Map.Entry<String, Object> e : ((Map<String, Object>) v).entrySet()) {
                if (!first) sb.append(',');
                first = false;
                quote(sb, e.getKey());
                sb.append(':');
                write(sb, e.getValue());
            }
            sb.append('}');
        } else if (v instanceof List) {
            sb.append('[');
            boolean first = true;
            for (Object o : (List<Object>) v) {
                if (!first) sb.append(',');
                first = false;
                write(sb, o);
            }
            sb.append(']');
        } else {
            quote(sb, String.valueOf(v));
        }
    }

    private static void quote(StringBuilder sb, String s) {
        sb.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                case '\b': sb.append("\\b"); break;
                case '\f': sb.append("\\f"); break;
                default:
                    if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                    else sb.append(c);
            }
        }
        sb.append('"');
    }

    /** Builds an ordered map from alternating key / value arguments. */
    public static Map<String, Object> map(Object... kv) {
        Map<String, Object> m = new LinkedHashMap<>();
        for (int i = 0; i + 1 < kv.length; i += 2) m.put(String.valueOf(kv[i]), kv[i + 1]);
        return m;
    }

    // ------------------------------------------------------------------ typed view
    /** Null-safe typed view over a JSON object (missing / wrong-typed fields return the default). */
    public static final class O {
        public final Map<String, Object> map;

        public O(Map<String, Object> m) {
            this.map = m != null ? m : new LinkedHashMap<String, Object>();
        }

        public boolean has(String k) {
            return map.containsKey(k) && map.get(k) != null;
        }

        public Object raw(String k) {
            return map.get(k);
        }

        public String str(String k, String def) {
            Object v = map.get(k);
            if (v == null) return def;
            if (v instanceof String) return (String) v;
            if (v instanceof Double) {
                double d = (Double) v;
                if (d == Math.rint(d) && Math.abs(d) < 1e15) return String.valueOf((long) d);
            }
            if (v instanceof Map || v instanceof List) return def;
            return String.valueOf(v);
        }

        public String str(String k) {
            return str(k, "");
        }

        public double num(String k, double def) {
            Object v = map.get(k);
            if (v instanceof Number) return ((Number) v).doubleValue();
            if (v instanceof String) {
                try {
                    return Double.parseDouble(((String) v).trim());
                } catch (NumberFormatException ignored) {
                }
            }
            return def;
        }

        public int integer(String k, int def) {
            Object v = map.get(k);
            if (v instanceof Number) return (int) Math.round(((Number) v).doubleValue());
            if (v instanceof String) {
                try {
                    return (int) Math.round(Double.parseDouble(((String) v).trim()));
                } catch (NumberFormatException ignored) {
                }
            }
            return def;
        }

        public long lng(String k, long def) {
            Object v = map.get(k);
            if (v instanceof Number) return ((Number) v).longValue();
            return def;
        }

        public boolean bool(String k, boolean def) {
            Object v = map.get(k);
            if (v instanceof Boolean) return (Boolean) v;
            if (v instanceof Number) return ((Number) v).doubleValue() != 0;
            if (v instanceof String) return "true".equalsIgnoreCase((String) v) || "1".equals(v);
            return def;
        }

        public O obj(String k) {
            Object v = map.get(k);
            return v instanceof Map ? new O(cast(v)) : new O(null);
        }

        @SuppressWarnings("unchecked")
        public List<Object> list(String k) {
            Object v = map.get(k);
            return v instanceof List ? (List<Object>) v : Collections.emptyList();
        }

        public List<O> objs(String k) {
            return objsOf(map.get(k));
        }

        @Override
        public String toString() {
            return stringify(map);
        }
    }

    /** Elements of a JSON array that are objects (others are skipped). */
    @SuppressWarnings("unchecked")
    public static List<O> objsOf(Object v) {
        List<O> out = new ArrayList<>();
        if (v instanceof List) {
            for (Object o : (List<Object>) v) if (o instanceof Map) out.add(new O(cast(o)));
        }
        return out;
    }
}
