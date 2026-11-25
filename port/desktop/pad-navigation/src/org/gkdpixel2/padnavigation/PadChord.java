package org.gkdpixel2.padnavigation;

import android.os.SystemClock;
import android.view.InputDevice;
import android.view.KeyEvent;

/** Decides the original R1 press before it is delivered to the foreground app. */
final class PadChord {
    private static final int CHORD_MS = 160;
    // Preserve a normal short tap across at least one emulated frame when its down was deferred.
    private static final int MIN_TAP_MS = 32;
    private static final int MAX_TAP_MS = 72;
    private static final int VIRTUAL_PRODUCT = 0x2102;
    private long reader;
    private int product;
    private int activeDevice = -1;
    private long functionTime = -1;
    private boolean captured;
    private long allowedAt;
    private long physicalDownTime;

    static { System.loadLibrary("padchord"); }
    private static native long openReader(int product);
    private static native long findFunctionDown(long reader, long r1Time, int windowMs);
    private static native void closeReader(long reader);

    static boolean isHandheld(InputDevice device) {
        return device != null && "gkd_pixel2_joypad".equals(device.getName())
                && device.getVendorId() == 1
                && (device.getProductId() == 1 || device.getProductId() == VIRTUAL_PRODUCT);
    }

    void connect() {
        int selected = 0;
        for (int id : InputDevice.getDeviceIds()) {
            InputDevice device = InputDevice.getDevice(id);
            if (!isHandheld(device)) continue;
            selected = device.getProductId();
            if (selected == VIRTUAL_PRODUCT) break;
        }
        if (selected != 0) open(selected);
    }

    private void open(int newProduct) {
        if (reader != 0 && product == newProduct) return;
        closeReader(reader);
        reader = openReader(newProduct);
        product = newProduct;
    }

    boolean shoulder(KeyEvent event) {
        int id = event.getDeviceId();
        if (event.getAction() == KeyEvent.ACTION_DOWN) {
            if (event.getRepeatCount() != 0) return activeDevice == id && captured;
            activeDevice = id;
            functionTime = -1;
            captured = false;
            long start = event.getEventTime();
            open(event.getDevice().getProductId());
            // Leave a wide margin to Android's 500 ms accessibility response deadline.
            if (reader != 0 && SystemClock.uptimeMillis() - start < 250) {
                long edge = findFunctionDown(reader, start, CHORD_MS);
                if (edge == -2) {
                    closeReader(reader);
                    reader = 0;
                } else if (edge >= 0 && SystemClock.uptimeMillis() - start < 300) {
                    captured = true;
                    functionTime = edge;
                }
            }
            allowedAt = SystemClock.uptimeMillis();
            physicalDownTime = start;
            return captured;
        }
        if (activeDevice != id) return false;
        boolean consume = captured;
        if (!consume && !event.isCanceled()) {
            long length = Math.max(MIN_TAP_MS, Math.min(MAX_TAP_MS,
                    event.getEventTime() - physicalDownTime));
            long now = SystemClock.uptimeMillis();
            long remaining = allowedAt + length - now;
            if (remaining > 0 && now - event.getEventTime() < 250) SystemClock.sleep(remaining);
        }
        activeDevice = -1;
        captured = false;
        return consume;
    }

    boolean takeFunction(KeyEvent event) {
        boolean match = functionTime >= 0 && event.getDeviceId() == activeDevice
                && Math.abs(event.getEventTime() - functionTime) <= 2;
        functionTime = -1;
        return match;
    }

    boolean ordinaryShoulderHeld(int deviceId) {
        return activeDevice == deviceId && !captured;
    }

    void reset() {
        activeDevice = -1;
        functionTime = -1;
        captured = false;
        allowedAt = 0;
        physicalDownTime = 0;
    }

    void close() {
        reset();
        closeReader(reader);
        reader = 0;
    }
}
