package com.android.quickstep.views;

import java.io.BufferedReader;
import java.io.StringReader;
import java.util.Objects;

final class CheckMemoryCounters {
    private static final String HEADER = "Filename\tType\tSize\tUsed\tPriority\n";
    private static final String ZRAM = "/dev/block/zram0 partition 744176 188416 100\n";
    private static final String TF = "/data/pixel2-swap/swapfile file 2097148 ";
    static BufferedReader input(String data) { return new BufferedReader(new StringReader(data)); }
    static void expect(String actual, String expected) {
        if (!Objects.equals(actual,expected)) throw new AssertionError(actual + " != " + expected);
    }
    public static void main(String[] args) throws Exception {
        expect(OverviewMemoryStats.availableRam(input("MemTotal: 992244 kB\nMemFree: 8240 kB\nMemAvailable: 373188 kB\n")), "364 / 969 MiB");
        expect(OverviewMemoryStats.availableRam(input("MemTotal: 992244 kB\nMemFree: 8240 kB\n")), "—");
        expect(OverviewMemoryStats.tfSwapUsage(input(HEADER + ZRAM + TF+"0 10\n")), "0 / 2048 MiB");
        expect(OverviewMemoryStats.tfSwapUsage(input(HEADER + TF+"131072 100\n"+ ZRAM)), "128 / 2048 MiB");
        expect(OverviewMemoryStats.tfSwapUsage(input(HEADER + ZRAM + TF+"4 10\n")), "<1 / 2048 MiB");
        expect(OverviewMemoryStats.tfSwapUsage(input(HEADER + ZRAM)), null);
        expect(OverviewMemoryStats.tfSwapUsage(input(HEADER)), null);
        expect(OverviewMemoryStats.tfSwapUsage(input("")), "—");
        System.out.println("8 checks passed");
    }
}
