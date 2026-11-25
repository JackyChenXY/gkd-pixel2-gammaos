package pixel2.platformtest;

import android.app.ActivityThread;
import android.content.pm.PackageInfo;
import android.os.RemoteException;
import android.system.ErrnoException;
import android.system.Os;
import android.system.StructStat;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import android.os.Process;
import android.util.Log;
import android.view.ThreadedRenderer;
import java.io.FileInputStream;
import java.io.BufferedReader;
import java.io.FileReader;
import java.io.IOException;
import java.nio.charset.StandardCharsets;

public final class OfficialSoftwareDecor {
    private static final String TAG = "Pixel2KrkrGL";
    private static boolean target() throws IOException {
        if (Process.myUid() != 10117) return false;
        try (FileInputStream in = new FileInputStream("/proc/self/cmdline")) {
            for (byte value : "org.github.krkr2".getBytes(StandardCharsets.US_ASCII))
                if (in.read() != value) return false;
            return in.read() == 0;
        }
    }
    private static String officialApk() throws RemoteException, IOException, NoSuchAlgorithmException, ErrnoException {
        PackageInfo pkg = ActivityThread.getPackageManager().getPackageInfo("org.github.krkr2", 0, 0);
        if (pkg == null || pkg.applicationInfo == null || pkg.applicationInfo.uid != Process.myUid()
                || !"1.4.4".equals(pkg.versionName) || pkg.applicationInfo.sourceDir == null
                || !pkg.applicationInfo.sourceDir.startsWith("/data/app/")
                || !pkg.applicationInfo.sourceDir.endsWith("/base.apk")) return null;
        StructStat before = Os.stat(pkg.applicationInfo.sourceDir);
        String expected = "e42f4c8a0468627e5fc6e40da0af7fa80fa9ee3c3a809d8f0d062a0c3923ffc2";
        MessageDigest hash = MessageDigest.getInstance("SHA-256");
        byte[] block = new byte[32768];
        try (FileInputStream apk = new FileInputStream(pkg.applicationInfo.sourceDir)) {
            int n;
            while ((n = apk.read(block)) != -1) hash.update(block, 0, n);
        }
        byte[] bytes = hash.digest();
        for (int i=0; i<bytes.length; i++) {
            int b = bytes[i] & 255;
            if (Character.digit(expected.charAt(2*i),16) != b/16
                    || Character.digit(expected.charAt(2*i+1),16) != b%16) return null;
        }
        StructStat after = Os.stat(pkg.applicationInfo.sourceDir);
        if (!identity(before).equals(identity(after))) return null;
        return pkg.applicationInfo.sourceDir + "|" + identity(after);

    }
    private static String identity(StructStat s) {
        return s.st_dev+":"+s.st_ino+":"+s.st_size+":"+s.st_mtime;
    }
    static String verifyForExec() throws RemoteException, IOException, NoSuchAlgorithmException, ErrnoException {
        return target() ? officialApk() : null;
    }
    private static boolean readyAfterAndroid() throws IOException {
        // WrapperInit may supply a distinct Java class loader for this second entry.
        if (!Integer.toString(Process.myPid()).equals(System.getenv("PIXEL2_KRKR_BRIDGE_READY"))) return false;
        boolean found=false;
        try (BufferedReader maps = new BufferedReader(new FileReader("/proc/self/maps"))) {
            for (String line; (line=maps.readLine())!=null;) {
                if (line.endsWith(" /vendor/lib/libgallium_dri.so")) return false;
                if (line.endsWith(" /odm/lib/libpixel2_krkr_v7.so")) found=true;
            }
        }
        return found && "survival".equals(System.getenv("PIXEL2_DEFER_AFBC"));
    }
    public static void main(String[] args) {
        try {
            if (target() && readyAfterAndroid()) {
                ThreadedRenderer.sRendererEnabled = false;
                if (!ThreadedRenderer.sRendererEnabled) {
                    EnginePressure.start();
                    Log.i(TAG,"official app ready; window software, game GLES on Mali");
                }
            } else Log.w(TAG,"preload unconfirmed after WrapperInit; platform defaults");
        } catch (IOException | RuntimeException | LinkageError e) {
            Log.w(TAG,"continuing with platform defaults",e);
        }
        Thread.currentThread().setContextClassLoader(ClassLoader.getSystemClassLoader());
        ActivityThread.main(args);
    }
}
