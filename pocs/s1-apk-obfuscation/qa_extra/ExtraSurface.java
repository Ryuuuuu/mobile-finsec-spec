package dev.finsec.s1.extra;

// Static-analysis fixture only; never executed on a device.
public final class ExtraSurface {
    public static void showLocalPage(android.webkit.WebView view) {
        view.loadData("<html><body>QA local page</body></html>", "text/html", "UTF-8");
    }
}
