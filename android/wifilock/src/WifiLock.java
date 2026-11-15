// SplitCPY Wi-Fi lock helper - runs on the device as the adb shell user via
// app_process (like scrcpy-server) and holds a high-performance Wi-Fi lock so
// the handheld's Wi-Fi stays out of power-save while streaming. Power save
// batches packets, which shows up as video stalls and audio dropouts.
//
// The lock lives as long as this process. SplitCPY keeps an `adb shell` open
// running it; when the stream stops (or SplitCPY dies) the shell closes, this
// process is killed and Android drops the lock through binder death.
//
// Build: see android/wifilock/build.py

import android.os.Binder;
import android.os.IBinder;
import android.os.IInterface;
import android.os.WorkSource;
import java.lang.reflect.Method;

public final class WifiLock {
    // WifiManager.WIFI_MODE_FULL_HIGH_PERF / WIFI_MODE_FULL_LOW_LATENCY
    private static final int MODE_HIGH_PERF = 3;
    private static final int MODE_LOW_LATENCY = 4;
    private static final String PKG = "com.android.shell";

    public static void main(String[] args) throws Exception {
        Class<?> sm = Class.forName("android.os.ServiceManager");
        IBinder svc = (IBinder) sm.getMethod("getService", String.class).invoke(null, "wifi");
        if (svc == null) {
            System.out.println("ERROR no wifi service");
            System.exit(2);
        }
        Class<?> stub = Class.forName("android.net.wifi.IWifiManager$Stub");
        IInterface wifi = (IInterface) stub.getMethod("asInterface", IBinder.class).invoke(null, svc);

        Method acquire = null;
        for (Method m : wifi.getClass().getMethods()) {
            if (m.getName().equals("acquireWifiLock")) {
                acquire = m;
                break;
            }
        }
        if (acquire == null) {
            System.out.println("ERROR acquireWifiLock not found");
            System.exit(3);
        }

        boolean ok = false;
        // High-perf turns off Wi-Fi power save; low-latency also does but
        // only counts while the owning app is in the foreground, so take both
        ok |= take(wifi, acquire, MODE_HIGH_PERF, "SplitCPY-hiperf");
        ok |= take(wifi, acquire, MODE_LOW_LATENCY, "SplitCPY-lowlat");
        if (!ok) {
            System.out.println("ERROR lock not granted");
            System.exit(4);
        }
        System.out.println("LOCKED");
        System.out.flush();
        // Hold until killed
        while (true) {
            Thread.sleep(Long.MAX_VALUE);
        }
    }

    private static boolean take(IInterface wifi, Method acquire, int mode, String tag) {
        try {
            Class<?>[] types = acquire.getParameterTypes();
            Object[] values = new Object[types.length];
            boolean sawString = false;
            for (int i = 0; i < types.length; i++) {
                Class<?> t = types[i];
                if (t == IBinder.class) values[i] = new Binder();
                else if (t == int.class) values[i] = mode;
                else if (t == String.class) {
                    // (tag, packageName) in that order on Android 12+
                    values[i] = sawString ? PKG : tag;
                    sawString = true;
                } else if (t == WorkSource.class) values[i] = null;
                else values[i] = null;  // Bundle extras etc.
            }
            Object r = acquire.invoke(wifi, values);
            boolean granted = !(r instanceof Boolean) || (Boolean) r;
            System.out.println((granted ? "OK " : "DENIED ") + tag);
            return granted;
        } catch (Throwable e) {
            Throwable c = e.getCause() != null ? e.getCause() : e;
            System.out.println("FAIL " + tag + ": " + c);
            return false;
        }
    }
}
