package org.gkdpixel2.padnavigation;

import android.content.Context;
import android.content.res.Configuration;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.view.Gravity;
import android.view.WindowManager;
import android.widget.LinearLayout;
import android.widget.TextView;

final class PadMenu {
    interface Action { void run(int index); }
    private static final int[] LABELS = {R.string.back, R.string.home, R.string.recents};
    private final Context context;
    private final WindowManager windows;
    private final Action action;
    private final TextView[] entries = new TextView[LABELS.length];
    private LinearLayout panel;
    private int selected;

    PadMenu(Context context, Action action) {
        this.context = context;
        windows = context.getSystemService(WindowManager.class);
        this.action = action;
    }

    int selected() { return selected; }
    boolean isOpen() { return panel != null; }

    void open() {
        if (isOpen()) return;
        selected = 1;
        panel = new LinearLayout(context);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setLayoutDirection(LinearLayout.LAYOUT_DIRECTION_LOCALE);
        panel.setPadding(dp(6), dp(6), dp(6), dp(6));
        panel.setBackground(shape(0xfa13222c, 0xff56717c, 10));
        for (int i = 0; i < LABELS.length; i++) {
            final int index = i;
            TextView entry = new TextView(context);
            entry.setText(LABELS[i]);
            entry.setGravity(Gravity.CENTER);
            entry.setTextSize(16);
            entry.setOnClickListener(v -> action.run(index));
            entries[i] = entry;
            panel.addView(entry, new LinearLayout.LayoutParams(-1, dp(40)));
        }
        TextView hint = new TextView(context);
        hint.setGravity(Gravity.CENTER);
        hint.setTextSize(12);
        hint.setTextColor(0xffd5e4e9);
        hint.setText(R.string.help);
        panel.addView(hint, new LinearLayout.LayoutParams(-1, dp(26)));
        updateSelection();

        WindowManager.LayoutParams layout = new WindowManager.LayoutParams(dp(156), -2,
                WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
                PixelFormat.TRANSLUCENT);
        boolean landscape = context.getResources().getConfiguration().orientation
                == Configuration.ORIENTATION_LANDSCAPE;
        layout.gravity = landscape ? Gravity.END | Gravity.CENTER_VERTICAL : Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL;
        if (landscape) layout.x = dp(6); else layout.y = dp(6);
        layout.setTitle("Pixel 2 gamepad navigation");
        windows.addView(panel, layout);
    }

    void move(int direction) {
        if (!isOpen()) return;
        selected = (selected + direction + LABELS.length) % LABELS.length;
        updateSelection();
    }
    void close() {
        if (panel == null) return;
        windows.removeViewImmediate(panel);
        panel = null;
        java.util.Arrays.fill(entries, null);
    }

    private void updateSelection() {
        for (int i = 0; i < entries.length; i++) {
            boolean active = i == selected;
            TextView entry = entries[i];
            entry.setSelected(active);
            entry.setTextColor(active ? 0xff09252d : Color.WHITE);
            entry.setTypeface(Typeface.DEFAULT, active ? Typeface.BOLD : Typeface.NORMAL);
            entry.setBackground(active ? shape(0xff8de7f4, 0xffc4f9ff, 6) : null);
        }
    }
    private GradientDrawable shape(int fill, int line, int radius) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(fill);
        drawable.setCornerRadius(dp(radius));
        drawable.setStroke(dp(1), line);
        return drawable;
    }
    private int dp(int value) {
        return Math.round(value * context.getResources().getDisplayMetrics().density);
    }
}
