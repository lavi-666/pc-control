package com.pccontrol.remote;

/**
 * Minimal SVG path-data parser (pure Java, no android.* imports, unit-tested on the JVM).
 * Lets the native player draw exactly the same Material/Feather icons that the
 * WebView interface of PC Control uses (inline SVG in assets/index.html).
 *
 * Supports M L H V C S Q T A Z (absolute and relative), implicit command repetition,
 * compact numbers ("-.5.5", "1e-3") and compact arc flags ("a1 1 0 001 1").
 * Quadratic curves and arcs are emitted as cubic Béziers.
 */
public final class PcSvgPath {

    public interface Sink {
        void moveTo(float x, float y);

        void lineTo(float x, float y);

        void cubicTo(float x1, float y1, float x2, float y2, float x, float y);

        void close();
    }

    private final String d;
    private int pos;

    private PcSvgPath(String d) {
        this.d = d;
    }

    public static void parse(String pathData, Sink sink) {
        new PcSvgPath(pathData).run(sink);
    }

    private void run(Sink s) {
        float cx = 0, cy = 0;          // current point
        float sx = 0, sy = 0;          // sub-path start
        float lcx = 0, lcy = 0;        // last control point (for S/T)
        char prev = ' ';
        char cmd = ' ';
        while (true) {
            skipSeparators();
            if (pos >= d.length()) break;
            char c = d.charAt(pos);
            if (isCommand(c)) {
                cmd = c;
                pos++;
            } else if (cmd == ' ') {
                throw new IllegalArgumentException("path must start with a command: " + d);
            } else if (cmd == 'M') {
                cmd = 'L';       // implicit lineto after moveto
            } else if (cmd == 'm') {
                cmd = 'l';
            } else if (cmd == 'Z' || cmd == 'z') {
                throw new IllegalArgumentException("number after Z at " + pos);
            }
            boolean rel = Character.isLowerCase(cmd);
            float ox = rel ? cx : 0, oy = rel ? cy : 0;
            switch (Character.toUpperCase(cmd)) {
                case 'M':
                    cx = ox + num();
                    cy = oy + num();
                    sx = cx;
                    sy = cy;
                    s.moveTo(cx, cy);
                    lcx = cx;
                    lcy = cy;
                    break;
                case 'L':
                    cx = ox + num();
                    cy = oy + num();
                    s.lineTo(cx, cy);
                    lcx = cx;
                    lcy = cy;
                    break;
                case 'H':
                    cx = ox + num();
                    s.lineTo(cx, cy);
                    lcx = cx;
                    lcy = cy;
                    break;
                case 'V':
                    cy = oy + num();
                    s.lineTo(cx, cy);
                    lcx = cx;
                    lcy = cy;
                    break;
                case 'C': {
                    float x1 = ox + num(), y1 = oy + num();
                    float x2 = ox + num(), y2 = oy + num();
                    float x = ox + num(), y = oy + num();
                    s.cubicTo(x1, y1, x2, y2, x, y);
                    lcx = x2;
                    lcy = y2;
                    cx = x;
                    cy = y;
                    break;
                }
                case 'S': {
                    char p = Character.toUpperCase(prev);
                    float x1 = (p == 'C' || p == 'S') ? 2 * cx - lcx : cx;
                    float y1 = (p == 'C' || p == 'S') ? 2 * cy - lcy : cy;
                    float x2 = ox + num(), y2 = oy + num();
                    float x = ox + num(), y = oy + num();
                    s.cubicTo(x1, y1, x2, y2, x, y);
                    lcx = x2;
                    lcy = y2;
                    cx = x;
                    cy = y;
                    break;
                }
                case 'Q': {
                    float qx = ox + num(), qy = oy + num();
                    float x = ox + num(), y = oy + num();
                    quad(s, cx, cy, qx, qy, x, y);
                    lcx = qx;
                    lcy = qy;
                    cx = x;
                    cy = y;
                    break;
                }
                case 'T': {
                    char p = Character.toUpperCase(prev);
                    float qx = (p == 'Q' || p == 'T') ? 2 * cx - lcx : cx;
                    float qy = (p == 'Q' || p == 'T') ? 2 * cy - lcy : cy;
                    float x = ox + num(), y = oy + num();
                    quad(s, cx, cy, qx, qy, x, y);
                    lcx = qx;
                    lcy = qy;
                    cx = x;
                    cy = y;
                    break;
                }
                case 'A': {
                    float rx = num(), ry = num(), rot = num();
                    boolean large = flag(), sweep = flag();
                    float x = ox + num(), y = oy + num();
                    arc(s, cx, cy, x, y, rx, ry, rot, large, sweep);
                    cx = x;
                    cy = y;
                    lcx = cx;
                    lcy = cy;
                    break;
                }
                case 'Z':
                    s.close();
                    cx = sx;
                    cy = sy;
                    lcx = cx;
                    lcy = cy;
                    break;
                default:
                    throw new IllegalArgumentException("unsupported command " + cmd);
            }
            prev = cmd;
        }
    }

    private static boolean isCommand(char c) {
        return "MmLlHhVvCcSsQqTtAaZz".indexOf(c) >= 0;
    }

    private void skipSeparators() {
        while (pos < d.length()) {
            char c = d.charAt(pos);
            if (c == ' ' || c == ',' || c == '\n' || c == '\r' || c == '\t') pos++;
            else break;
        }
    }

    private boolean flag() {
        skipSeparators();
        if (pos >= d.length()) throw new IllegalArgumentException("missing arc flag");
        char c = d.charAt(pos++);
        if (c == '0') return false;
        if (c == '1') return true;
        throw new IllegalArgumentException("bad arc flag '" + c + "' at " + (pos - 1));
    }

    private float num() {
        skipSeparators();
        int start = pos;
        int n = d.length();
        if (pos < n && (d.charAt(pos) == '-' || d.charAt(pos) == '+')) pos++;
        boolean dot = false, digits = false;
        while (pos < n) {
            char c = d.charAt(pos);
            if (c >= '0' && c <= '9') {
                digits = true;
                pos++;
            } else if (c == '.' && !dot) {
                dot = true;
                pos++;
            } else {
                break;
            }
        }
        if (pos < n && (d.charAt(pos) == 'e' || d.charAt(pos) == 'E') && digits) {
            int save = pos;
            pos++;
            if (pos < n && (d.charAt(pos) == '-' || d.charAt(pos) == '+')) pos++;
            boolean expDigits = false;
            while (pos < n && d.charAt(pos) >= '0' && d.charAt(pos) <= '9') {
                pos++;
                expDigits = true;
            }
            if (!expDigits) pos = save;
        }
        if (!digits) throw new IllegalArgumentException("number expected at " + start + " in " + d);
        return Float.parseFloat(d.substring(start, pos));
    }

    private static void quad(Sink s, float x0, float y0, float qx, float qy, float x, float y) {
        s.cubicTo(x0 + 2f / 3f * (qx - x0), y0 + 2f / 3f * (qy - y0),
                x + 2f / 3f * (qx - x), y + 2f / 3f * (qy - y), x, y);
    }

    /** SVG endpoint arc -> center parameterisation -> cubic segments of at most 90 degrees. */
    static void arc(Sink s, float x0, float y0, float x, float y, float rx, float ry,
                    float rotDeg, boolean large, boolean sweep) {
        if (x0 == x && y0 == y) return;
        rx = Math.abs(rx);
        ry = Math.abs(ry);
        if (rx == 0 || ry == 0) {
            s.lineTo(x, y);
            return;
        }
        double phi = Math.toRadians(rotDeg % 360.0);
        double cos = Math.cos(phi), sin = Math.sin(phi);
        double dx2 = (x0 - x) / 2.0, dy2 = (y0 - y) / 2.0;
        double x1p = cos * dx2 + sin * dy2;
        double y1p = -sin * dx2 + cos * dy2;
        double rxs = (double) rx * rx, rys = (double) ry * ry;
        double lambda = (x1p * x1p) / rxs + (y1p * y1p) / rys;
        if (lambda > 1) {
            double k = Math.sqrt(lambda);
            rx *= k;
            ry *= k;
            rxs = (double) rx * rx;
            rys = (double) ry * ry;
        }
        double num = rxs * rys - rxs * y1p * y1p - rys * x1p * x1p;
        double den = rxs * y1p * y1p + rys * x1p * x1p;
        double coef = (den == 0) ? 0 : Math.sqrt(Math.max(0, num / den));
        if (large == sweep) coef = -coef;
        double cxp = coef * (rx * y1p / ry);
        double cyp = coef * -(ry * x1p / rx);
        double cxc = cos * cxp - sin * cyp + (x0 + x) / 2.0;
        double cyc = sin * cxp + cos * cyp + (y0 + y) / 2.0;

        double ux = (x1p - cxp) / rx, uy = (y1p - cyp) / ry;
        double vx = (-x1p - cxp) / rx, vy = (-y1p - cyp) / ry;
        double theta1 = Math.atan2(uy, ux);
        double dtheta = Math.atan2(ux * vy - uy * vx, ux * vx + uy * vy);
        if (!sweep && dtheta > 0) dtheta -= 2 * Math.PI;
        else if (sweep && dtheta < 0) dtheta += 2 * Math.PI;

        int segs = (int) Math.ceil(Math.abs(dtheta) / (Math.PI / 2) - 1e-7);
        if (segs < 1) segs = 1;
        double delta = dtheta / segs;
        double t = 4.0 / 3.0 * Math.tan(delta / 4);
        double a = theta1;
        double ex = x0, ey = y0;
        for (int i = 0; i < segs; i++) {
            double cosA = Math.cos(a), sinA = Math.sin(a);
            double b = a + delta;
            double cosB = Math.cos(b), sinB = Math.sin(b);
            // derivatives on the unit circle, scaled and rotated
            double d1x = -rx * sinA, d1y = ry * cosA;
            double d2x = -rx * sinB, d2y = ry * cosB;
            double c1x = ex + t * (cos * d1x - sin * d1y);
            double c1y = ey + t * (sin * d1x + cos * d1y);
            double px = cxc + cos * rx * cosB - sin * ry * sinB;
            double py = cyc + sin * rx * cosB + cos * ry * sinB;
            if (i == segs - 1) {
                px = x;
                py = y;
            }
            double c2x = px - t * (cos * d2x - sin * d2y);
            double c2y = py - t * (sin * d2x + cos * d2y);
            s.cubicTo((float) c1x, (float) c1y, (float) c2x, (float) c2y, (float) px, (float) py);
            ex = px;
            ey = py;
            a = b;
        }
    }
}
