package com.pccontrol.remote;

/**
 * Чистая (без Android) математика раскладки узких строк плеера — проверяется JVM-тестами.
 * Все размеры в пикселях.
 */
final class PcLayoutMath {
    private PcLayoutMath() {}

    // индексы результата transport()
    static final int T_GAP = 0, T_CENTER_LEFT = 1, T_ICON_ONLY = 2, T_PILL_W = 3, T_CENTER_W = 4;

    /**
     * Строка управления плеером: [режим] · [назад ◯ вперёд] · [пилюля «Очередь»]
     * (web .ytm-transport: grid 1fr auto 1fr). Правила:
     * 1) центр по центру строки, промежуток между кнопками центра — до gapMax, но не меньше gapMin;
     * 2) не помещается — центральная группа сдвигается влево (как сетка в вебе), между группами
     *    остаётся sideGap;
     * 3) и так не помещается — у пилюли остаётся только значок (pillIconW).
     * Возвращает {gap, centerLeft, iconOnly(0/1), pillW, centerW}. Группы никогда не перекрываются,
     * если ширина ≥ modeW + 2·sideGap + centerW(gapMin) + pillIconW.
     */
    static int[] transport(int width, int modeW, int sideBtnW, int playW, int pillFullW, int pillIconW,
                           int gapMax, int gapMin, int sideGap) {
        int[] r = place(width, modeW, sideBtnW, playW, pillFullW, gapMax, gapMin, sideGap);
        if (r != null) return new int[]{r[0], r[1], 0, pillFullW, r[2]};
        r = place(width, modeW, sideBtnW, playW, pillIconW, gapMax, gapMin, sideGap);
        if (r != null) return new int[]{r[0], r[1], 1, pillIconW, r[2]};
        // крайний случай (меньше ~240 dp): минимальные промежутки, центр между краями
        int cw = 2 * sideBtnW + playW + 2 * gapMin;
        int left = Math.max(0, (width - cw) / 2);
        return new int[]{gapMin, left, 1, pillIconW, cw};
    }

    /** {gap, centerLeft, centerW} или null, если пилюля такой ширины не помещается. */
    private static int[] place(int width, int modeW, int sideBtnW, int playW, int pillW,
                               int gapMax, int gapMin, int sideGap) {
        int fixed = 2 * sideBtnW + playW;
        int side = Math.max(modeW, pillW) + sideGap;
        // по центру: (width - C) / 2 >= side  →  C <= width - 2·side
        int gap = Math.min(gapMax, (width - 2 * side - fixed) / 2);
        if (gap >= gapMin) {
            int cw = fixed + 2 * gap;
            return new int[]{gap, (width - cw) / 2, cw};
        }
        // со сдвигом влево: центр между [режим + sideGap] и [пилюля − sideGap]
        int cw = fixed + 2 * gapMin;
        int leftLimit = modeW + sideGap;
        int rightLimit = width - pillW - sideGap;
        if (rightLimit - leftLimit < cw) return null;
        int left = Math.max(leftLimit, Math.min((width - cw) / 2, rightLimit - cw));
        return new int[]{gapMin, left, cw};
    }

    /**
     * Шапка очереди: [вкладки] … [подпись источника] [кнопки]. Подпись остаётся в строке,
     * только если целиком помещается между вкладками и кнопками; иначе уходит на свою строку
     * под вкладками (вкладки никогда не перекрываются).
     */
    static boolean queueCountInline(int width, int tabsW, int countW, int buttonsW, int gap) {
        if (countW <= 0) return true;
        return tabsW + gap + countW + buttonsW <= width;
    }

    /** Ширина, доступная вкладкам (они сжимаются только если не влезают даже без подписи). */
    static int queueTabsMax(int width, int buttonsW, int gap) {
        return Math.max(0, width - buttonsW - (buttonsW > 0 ? gap : 0));
    }
}
