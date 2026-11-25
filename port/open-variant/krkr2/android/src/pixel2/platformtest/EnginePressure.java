package pixel2.platformtest;

import android.app.Activity;
import android.app.ActivityThread;
import android.app.Application;
import android.os.Handler;
import android.os.Looper;
import android.os.Process;
import android.os.SystemClock;
import android.util.Log;
import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.IOException;
import java.lang.reflect.Field;
import java.util.concurrent.atomic.AtomicBoolean;

/** An opt-in, process-local trial of the game's existing ComponentCallbacks.onLowMemory. */
public final class EnginePressure implements Runnable {
    private static final String TAG = "P2Trim", PKG = "org.github.krkr2";
    private static final String ENGINE_ACTIVITY = "org.tvp.kirikiri2.KR2Activity";
    private static final long MIB = 1024L * 1024L;
    private static final long POLL_MS = 1500, COOLDOWN_MS = 6000;
    private static final int MAX_DELIVERIES = 180;
    private final AtomicBoolean posted = new AtomicBoolean();
    private volatile boolean done;
    private volatile long lastDelivery;
    private int deliveries;
    private Field singleton;

    static void start() {
        EnginePressure watcher = new EnginePressure();
        Thread t = new Thread(watcher, "P2-game-pressure");
        t.setDaemon(true);
        t.start();
    }

    private static long readNumber(File f, String key) {
        try (BufferedReader r = new BufferedReader(new FileReader(f))) {
            String line;
            while ((line = r.readLine()) != null) {
                if (!line.startsWith(key)) continue;
                String[] fields = line.trim().split("\\s+");
                if (fields.length >= 2 && key.equals(fields[0])) return Long.parseLong(fields[1]);
            }
        } catch (IOException | SecurityException | NumberFormatException ignored) { }
        return -1;
    }

    private static File memoryGroup() {
        String prefix = "/apps/uid_" + Process.myUid() + "/pid_";
        try (BufferedReader r = new BufferedReader(new FileReader("/proc/self/cgroup"))) {
            String line;
            while ((line = r.readLine()) != null) {
                String[] cols = line.split(":", 3);
                if (cols.length != 3 || !"memory".equals(cols[1]) || !cols[2].startsWith(prefix)) continue;
                if (cols[2].substring(prefix.length()).matches("[0-9]+")) {
                    return new File("/dev/memcg" + cols[2] + "/memory.stat");
                }
            }
        } catch (IOException | SecurityException ignored) { }
        return null;
    }

    static boolean shouldNotify(long availableKb, long pinnedBytes) {
        return (availableKb >= 0 && availableKb <= 125L * 1024L)
                || pinnedBytes >= 230L * MIB
                || (availableKb >= 0 && availableKb <= 210L * 1024L && pinnedBytes >= 135L * MIB);
    }

    public void run() {
        File meminfo = new File("/proc/meminfo");
        try {
            Thread.sleep(15000);
            File group = memoryGroup();
            Log.i(TAG, "watch pid=" + Process.myPid() + " group=" + group + " cooldownMs=" + COOLDOWN_MS);
            long reportAt = 0;
            while (!done) {
                long now = SystemClock.elapsedRealtime();
                long avail = readNumber(meminfo, "MemAvailable:");
                long pinned = group == null ? -1 : readNumber(group, "unevictable");
                if (now >= reportAt) {
                    Log.i(TAG, "sample availKiB=" + avail + " unevictBytes=" + pinned);
                    reportAt = now + 15000;
                }
                Looper looper = Looper.getMainLooper();
                if (looper != null && shouldNotify(avail, pinned) && now-lastDelivery >= COOLDOWN_MS
                        && posted.compareAndSet(false, true)) {
                    if (!new Handler(looper).post(() -> notifyGame(avail, pinned))) posted.set(false);
                }
                Thread.sleep(POLL_MS);
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } catch (RuntimeException | LinkageError e) {
            Log.e(TAG, "pressure monitor stopped", e);
        }
    }

    private void notifyGame(long avail, long pinned) {
        try {
            // Read and call the live activity only on its main thread. Its implementation
            // delegates this standard Android event to the engine's own event thread.
            if (Looper.myLooper() != Looper.getMainLooper()) return;
            Application app = ActivityThread.currentApplication();
            if (app == null || !PKG.equals(app.getPackageName())) return;
            if (singleton == null) {
                Class<?> type = Class.forName(ENGINE_ACTIVITY, false, app.getClassLoader());
                singleton = type.getField("sInstance");
            }
            Object instance = singleton.get(null);
            if (!(instance instanceof Activity)) return;
            Activity activity = (Activity)instance;
            if (activity.getApplication() != app || !PKG.equals(activity.getPackageName())
                    || activity.isDestroyed() || activity.isFinishing() || !activity.hasWindowFocus()) return;
            long now = SystemClock.elapsedRealtime();
            if (now - lastDelivery < COOLDOWN_MS || deliveries >= MAX_DELIVERIES) return;
            lastDelivery = now;
            ++deliveries;
            activity.onLowMemory();
            Log.i(TAG, "delivered n=" + deliveries + " availKiB=" + avail + " unevictBytes=" + pinned
                    + " target=" + activity.getClass().getName() + " pid=" + Process.myPid());
            if (deliveries == MAX_DELIVERIES) done = true;
        } catch (ReflectiveOperationException | RuntimeException | LinkageError e) {
            done = true;
            Log.e(TAG, "official callback unavailable; stopping", e);
        } finally {
            posted.set(false);
        }
    }
}
