package com.pccontrol.remote;

/**
 * Громкость демонстрации 0–200 % для 16-битного PCM (little-endian, любое число каналов).
 * <ul>
 *   <li>Выше 100 % — настоящее усиление сигнала, а не только цифры на ползунке.</li>
 *   <li>Пиковый лимитер: если усиленный сигнал превысил бы потолок CEIL, общий коэффициент
 *       мгновенно снижается ровно настолько, чтобы пик не вышел за потолок, а затем плавно
 *       (~150 мс) возвращается. Обрезания пиков (хрипа) и переполнения нет; тихие места
 *       действительно звучат вдвое громче, громкие — плотнее, но без искажений.</li>
 *   <li>Изменение громкости плавно растягивается на один буфер — без щелчков.</li>
 *   <li>До 100 % исходный сигнал не искажается (только линейное ослабление).</li>
 * </ul>
 * Чистая Java — проверяется JVM-тестами без Android.
 */
public final class PcAudioGain {
    public static final int MAX_PERCENT = 200;
    /** Потолок пиков (доля полной шкалы) — запас от переполнения int16. */
    static final float CEIL = 0.97f;
    /** Скорость восстановления лимитера на сэмпл (≈150 мс при 48 кГц стерео). */
    private static final float RELEASE = (float) (1.0 - Math.exp(-1.0 / (0.150 * 96000.0)));

    private float current = -1f;
    private float env = 1f;

    public static float percentToGain(int percent, boolean muted) {
        if (muted) return 0f;
        return Math.max(0, Math.min(MAX_PERCENT, percent)) / 100f;
    }

    /** Усиление, применённое последним (для тестов/диагностики). */
    public float currentGain() {
        return current;
    }

    /** Применяет усиление к буферу на месте. len — число байт (чётное). */
    public void apply(byte[] buf, int len, float target) {
        float from = current < 0 ? target : current;
        current = target;
        if (from == 1f && target == 1f && env >= 1f) return;
        int samples = len / 2;
        if (samples == 0) return;
        if (from == 0f && target == 0f) {
            java.util.Arrays.fill(buf, 0, samples * 2, (byte) 0);
            return;
        }
        float step = (target - from) / samples;
        float g = from;
        for (int i = 0; i < samples; i++) {
            int lo = buf[2 * i] & 0xFF;
            int hi = buf[2 * i + 1];
            float y = (short) ((hi << 8) | lo) / 32768f * g;
            // лимитер: восстановление к 1, но не выше требуемого для этого сэмпла
            env += (1f - env) * RELEASE;
            float a = Math.abs(y);
            if (a * env > CEIL) env = CEIL / a;
            y *= env;
            int s = Math.round(y * 32767f);
            if (s > 32767) s = 32767;
            else if (s < -32768) s = -32768;
            buf[2 * i] = (byte) s;
            buf[2 * i + 1] = (byte) (s >> 8);
            g += step;
        }
    }
}
