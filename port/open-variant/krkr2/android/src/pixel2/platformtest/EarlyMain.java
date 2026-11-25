package pixel2.platformtest;

import android.os.Process;
import android.os.RemoteException;
import android.system.ErrnoException;
import android.system.Os;
import android.util.Log;
import com.android.internal.os.WrapperInit;
import java.io.BufferedReader;
import java.io.FileReader;
import java.io.IOException;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Map;

/** Verify the installed app, then exec the original ARM runtime with its immutable system bridge. */
public final class EarlyMain {
    private static final String EXE="/system/bin/app_process32";
    private static final String JAR="/system/etc/pixel2-krkr/official-software-decor.jar";
    private static final String LIB="/system/lib/libpixel2_krkr_bootstrap.so";
    private EarlyMain() {}
    private static boolean numeric(String s) {return s!=null && s.matches("[0-9]{1,8}");}
    static boolean hasRealPreload(String value) {
        if (value == null) return false;
        for (int i=0;i<value.length();i++) {
            char c=value.charAt(i);
            if (c!=':' && c!=' ' && !(c>='\t' && c<='\r')) return true;
        }
        return false;
    }
    private static long pipeFlags(String fd) throws IOException {
        if ("0".equals(fd)) return 0;
        try (BufferedReader r=new BufferedReader(new FileReader("/proc/self/fdinfo/"+fd))) {
            for(String s;(s=r.readLine())!=null;) if(s.startsWith("flags:"))
                return Long.parseLong(s.substring(6).trim(),8);
        }
        return -1;
    }
    private static boolean profileArgs(String[] a) {
        return a.length>=5 && numeric(a[0]) && numeric(a[1]) && "-cp".equals(a[2])
            && JAR.equals(a[3]) && "pixel2.platformtest.OfficialSoftwareDecor".equals(a[4]);
    }
    public static void main(String[] a) {
        boolean profile=profileArgs(a);
        boolean pipeNumeric = a.length>0 && numeric(a[0]);
        boolean sdkNumeric = a.length>1 && numeric(a[1]);
        boolean realPreload=hasRealPreload(System.getenv("LD_PRELOAD"));
        Log.i("Pixel2KrkrGL","startup guard profileArgs="+profile+" pipeNumeric="+pipeNumeric+
            " sdkNumeric="+sdkNumeric+" realPreload="+realPreload);
        if(profile) {
            try {
                String source=OfficialSoftwareDecor.verifyForExec();
                Log.i("Pixel2KrkrGL","APK identity accepted="+(source!=null));
                long flags=pipeFlags(a[0]);
                boolean survives=flags>=0 && (flags & 02000000L)==0;
                Log.i("Pixel2KrkrGL","Zygote pipe fd="+a[0]+" flags="+
                    (flags<0?"unavailable":"0"+Long.toOctalString(flags))+" survivesExec="+survives);
                if(source!=null && survives && !realPreload) {
                    ArrayList<String> args=new ArrayList<>(Arrays.asList(EXE,"-Xcompiler-option",
                        "--generate-mini-debug-info","/system/bin","--application","--nice-name=org.github.krkr2",
                        "com.android.internal.os.WrapperInit"));
                    args.addAll(Arrays.asList(a));
                    ArrayList<String> env=new ArrayList<>();
                    for(Map.Entry<String,String> e:System.getenv().entrySet()) {
                        String k=e.getKey();
                        if(!"CLASSPATH".equals(k) && !"LD_PRELOAD".equals(k) && !k.startsWith("PIXEL2_KRKR_"))
                            env.add(k+"="+e.getValue());
                    }
                    env.add("LD_PRELOAD="+LIB);
                    env.add("PIXEL2_KRKR_VERIFIED_PID="+Process.myPid());
                    env.add("PIXEL2_KRKR_VERIFIED_SOURCE="+source);
                    Log.i("Pixel2KrkrGL","official APK verified; executing platform bridge pid="+Process.myPid());
                    Os.execve(EXE,args.toArray(new String[0]),env.toArray(new String[0]));
                }
            } catch(IOException | RemoteException | NoSuchAlgorithmException | ErrnoException | RuntimeException | LinkageError e) {
                Log.w("Pixel2KrkrGL","stock fallback on launch handoff",e);
            }
            String[] stock=new String[a.length-2];
            stock[0]=a[0];stock[1]=a[1];stock[2]="android.app.ActivityThread";
            System.arraycopy(a,5,stock,3,a.length-5);
            WrapperInit.main(stock);
        } else {
            WrapperInit.main(a);
        }
    }
}
