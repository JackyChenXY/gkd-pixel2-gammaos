package org.gkdpixel2.padnavigation;

import android.accessibilityservice.AccessibilityService;
import android.app.KeyguardManager;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.res.Configuration;
import android.util.SparseBooleanArray;
import android.view.KeyEvent;
import android.view.accessibility.AccessibilityEvent;
import android.widget.Toast;

public final class PadNavigationService extends AccessibilityService {
    private final SparseBooleanArray ownedKeys = new SparseBooleanArray();
    private final PadChord chord = new PadChord();
    private boolean receiverRegistered;
    private PadMenu menu;
    private KeyguardManager keyguard;
    private final BroadcastReceiver screenOff = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) {
            resetInput();
        }
    };

    @Override protected void onServiceConnected() {
        chord.connect();
        if (!receiverRegistered) {
            registerReceiver(screenOff, new IntentFilter(Intent.ACTION_SCREEN_OFF));
            receiverRegistered = true;
        }
        keyguard = getSystemService(KeyguardManager.class);
        if (menu == null) menu = new PadMenu(this, this::activate);
    }

    @Override protected boolean onKeyEvent(KeyEvent event) {
        if (menu == null || !PadChord.isHandheld(event.getDevice())) return false;
        int key = event.getKeyCode();
        boolean down = event.getAction() == KeyEvent.ACTION_DOWN;
        boolean up = event.getAction() == KeyEvent.ACTION_UP;
        if (!down && !up) return false;

        if (keyguard != null && keyguard.isKeyguardLocked()) {
            resetInput();
            return false;
        }
        if (key == KeyEvent.KEYCODE_BUTTON_R1) {
            return chord.shoulder(event);
        }
        if (up) {
            if (!ownedKeys.get(key)) return false;
            ownedKeys.delete(key);
            if (!event.isCanceled() && menu.isOpen()) {
                if (key == KeyEvent.KEYCODE_BUTTON_A || key == KeyEvent.KEYCODE_DPAD_CENTER) {
                    activate(menu.selected());
                } else if (key == KeyEvent.KEYCODE_BUTTON_B || key == KeyEvent.KEYCODE_BACK) {
                    menu.close();
                }
            }
            return true;
        }
        if (key == KeyEvent.KEYCODE_MENU) {
            if (event.getRepeatCount() != 0) return ownedKeys.get(key);
            boolean shortcut = chord.takeFunction(event);
            // Once the game owns R1, the rest of that hold cannot open navigation.
            if (!shortcut && chord.ordinaryShoulderHeld(event.getDeviceId())) {
                ownedKeys.put(key, true);
                return true;
            }
            if (shortcut || menu.isOpen()) {
                if (menu.isOpen()) menu.close(); else menu.open();
                ownedKeys.put(key, true);
                return true;
            }
        }
        if (!menu.isOpen()) return ownedKeys.get(key);
        switch (key) {
            case KeyEvent.KEYCODE_DPAD_UP:
            case KeyEvent.KEYCODE_DPAD_LEFT:
                menu.move(-1);
                break;
            case KeyEvent.KEYCODE_DPAD_DOWN:
            case KeyEvent.KEYCODE_DPAD_RIGHT:
                menu.move(1);
                break;
            case KeyEvent.KEYCODE_BUTTON_A:
            case KeyEvent.KEYCODE_DPAD_CENTER:
            case KeyEvent.KEYCODE_BUTTON_B:
            case KeyEvent.KEYCODE_BACK:
                break;
            default:
                return false;
        }
        ownedKeys.put(key, true);
        return true;
    }

    private void activate(int index) {
        menu.close();
        int action = index == 0 ? GLOBAL_ACTION_BACK : index == 1 ? GLOBAL_ACTION_HOME : GLOBAL_ACTION_RECENTS;
        if (!performGlobalAction(action)) {
            Toast.makeText(this, R.string.action_unavailable, Toast.LENGTH_SHORT).show();
        }
    }

    private void resetInput() {
        chord.reset();
        ownedKeys.clear();
        if (menu != null) menu.close();
    }

    @Override public void onConfigurationChanged(Configuration configuration) {
        super.onConfigurationChanged(configuration);
        resetInput();
    }
    @Override public void onAccessibilityEvent(AccessibilityEvent event) {}
    @Override public void onInterrupt() { resetInput(); }
    @Override public boolean onUnbind(Intent intent) {
        resetInput();
        chord.close();
        return super.onUnbind(intent);
    }
    @Override public void onDestroy() {
        resetInput();
        chord.close();
        if (receiverRegistered) unregisterReceiver(screenOff);
        super.onDestroy();
    }
}
