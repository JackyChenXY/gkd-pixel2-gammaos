// SPDX-License-Identifier: GPL-2.0-or-later
package org.ppsspp.ppsspp;

import android.app.Activity;
import android.graphics.Rect;
import android.opengl.GLSurfaceView;
import android.util.Log;
import android.view.Surface;
import android.view.SurfaceHolder;
import javax.microedition.khronos.egl.EGL10;
import javax.microedition.khronos.egl.EGLConfig;
import javax.microedition.khronos.egl.EGLDisplay;
import javax.microedition.khronos.egl.EGLSurface;

final class Pixel2Presentation implements GLSurfaceView.EGLWindowSurfaceFactory {
    private static final String TAG = "Pixel2G31";
    private long bridge;
    private Surface input;

    static void configure(GLSurfaceView view, Activity activity) {
        // Use the same game render target in both experiments.
        view.setEGLConfigChooser(8, 8, 8, 8, 16, 0);
        boolean g31Launcher = activity.getIntent().getComponent() != null &&
                "org.ppsspp.ppsspp.Pixel2G31Launcher".equals(activity.getIntent().getComponent().getClassName());
        boolean direct = activity.getIntent().getBooleanExtra("pixel2G31", g31Launcher);
        if (direct) {
            try {
                System.loadLibrary("pixel2_ppsspp");
                view.setEGLWindowSurfaceFactory(new Pixel2Presentation());
            } catch (LinkageError e) {
                Log.e(TAG, "Presenter unavailable, using Android presentation", e);
                return;
            }
        }
        Log.i(TAG, direct ? "Requested G31 presentation" : "Using Android presentation");
    }

    private static native long open(Surface output, int width, int height);
    private static native Surface inputSurface(long bridge);
    private static native void close(long bridge);

    private void release() {
        if (input != null) {
            input.release();
            input = null;
        }
        if (bridge != 0) {
            close(bridge);
            bridge = 0;
        }
    }

    @Override
    public EGLSurface createWindowSurface(EGL10 egl, EGLDisplay display, EGLConfig config, Object window) {
        if (window instanceof SurfaceHolder) {
            SurfaceHolder holder = (SurfaceHolder) window;
            Rect frame = holder.getSurfaceFrame();
            if (frame.width() > frame.height() && frame.height() > 0) {
                bridge = open(holder.getSurface(), frame.width(), frame.height());
                if (bridge != 0) {
                    input = inputSurface(bridge);
                    if (input != null) {
                        EGLSurface surface = egl.eglCreateWindowSurface(display, config, input, null);
                        if (surface != null && surface != EGL10.EGL_NO_SURFACE) {
                            Log.i(TAG, "Game EGL surface connected to the G31 presenter");
                            return surface;
                        }
                        Log.e(TAG, "Game EGL surface creation failed 0x" + Integer.toHexString(egl.eglGetError()));
                    }
                    release();
                }
            }
        }
        Log.w(TAG, "Using original EGL window for this surface");
        return egl.eglCreateWindowSurface(display, config, window, null);
    }

    @Override
    public void destroySurface(EGL10 egl, EGLDisplay display, EGLSurface surface) {
        try {
            egl.eglDestroySurface(display, surface);
        } finally {
            release();
        }
    }
}
