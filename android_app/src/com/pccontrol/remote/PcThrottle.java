package com.pccontrol.remote;

/**
 * Троттлинг запросов при перетаскивании ползунка (громкость приложений, громкость демонстрации):
 * первое значение уходит сразу, дальше — не чаще раза в intervalMs, и всегда отправляется
 * последнее значение (хвостом). commit() отправляет значение немедленно и отменяет хвост.
 * Чистая Java: часы и планировщик передаются снаружи (Handler на Android, фейк в JVM-тестах).
 */
final class PcThrottle {
    interface Clock {
        long now();
    }

    interface Scheduler {
        void schedule(Runnable r, long delayMs);
    }

    private final long interval;
    private final Clock clock;
    private final Scheduler scheduler;
    private long lastRun = Long.MIN_VALUE / 2;
    private Runnable pending;
    private boolean timerArmed;

    PcThrottle(long intervalMs, Clock clock, Scheduler scheduler) {
        this.interval = intervalMs;
        this.clock = clock;
        this.scheduler = scheduler;
    }

    /** Промежуточное значение (onInput): сразу или хвостом, последнее побеждает. */
    void submit(Runnable action) {
        long now = clock.now();
        if (!timerArmed && now - lastRun >= interval) {
            pending = null;
            lastRun = now;
            action.run();
            return;
        }
        pending = action;
        if (!timerArmed) {
            timerArmed = true;
            scheduler.schedule(new Runnable() {
                @Override
                public void run() {
                    timerArmed = false;
                    Runnable p = pending;
                    pending = null;
                    if (p != null) {
                        lastRun = clock.now();
                        p.run();
                    }
                }
            }, Math.max(0, lastRun + interval - now));
        }
    }

    /** Итоговое значение (onCommit / кнопка): немедленно, хвост отменяется. */
    void commit(Runnable action) {
        pending = null;
        lastRun = clock.now();
        action.run();
    }

    boolean hasPending() {
        return pending != null;
    }
}
