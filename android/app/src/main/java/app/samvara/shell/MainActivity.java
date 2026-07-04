package app.samvara.shell;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.job.JobInfo;
import android.app.job.JobScheduler;
import android.content.ComponentName;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.webkit.WebResourceRequest;
import android.widget.FrameLayout;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;
import org.json.JSONTokener;

/**
 * The whole UI is https://samvara.app in a WebView, so every GitHub Pages
 * deploy updates this app with no reinstall. The native side does exactly two
 * things: harvest the session token out of the page's localStorage (so the
 * background poller can call the API), and keep the poller scheduled.
 */
public class MainActivity extends Activity {

    static final String PREFS = "samvara";
    static final String PREF_TOKEN = "apiToken";
    static final String PREF_API_BASE = "apiBase";
    static final String SITE = "https://samvara.app/";
    static final int JOB_ID = 1;
    static final long POLL_INTERVAL_MS = 15 * 60 * 1000L;   // JobScheduler minimum
    static final int PAGE_BG_LIGHT = 0xFFF4F2EE;   // the page's light --bg
    static final int PAGE_BG_DARK = 0xFF161713;    // the page's dark --bg
    static final String PREF_DARK = "darkTheme";

    private WebView web;
    private FrameLayout frame;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        web = new WebView(this);
        // Pad a wrapper, not the WebView: WebView does not reliably honor its
        // own padding, which left the page top under the status-bar clock.
        frame = new FrameLayout(this);
        frame.addView(web);
        setContentView(frame);

        // targetSdk 35 enforces edge-to-edge: inset the frame by the system
        // bars. Colors and icon appearance follow the page theme.
        if (Build.VERSION.SDK_INT >= 30) {
            frame.setOnApplyWindowInsetsListener((v, insets) -> {
                android.graphics.Insets sb = insets.getInsets(
                        WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                v.setPadding(sb.left, sb.top, sb.right, sb.bottom);
                return WindowInsets.CONSUMED;
            });
        } else {
            frame.setFitsSystemWindows(true);
        }
        // Last known theme, so a dark-mode user doesn't get a light flash
        // before the page boots and re-syncs over the bridge.
        applyTheme(getSharedPreferences(PREFS, MODE_PRIVATE).getBoolean(PREF_DARK, false));

        // The page calls window.SamvaraShell.onTheme('1'|'0') on boot and on
        // every Dark/Light toggle (see setTheme in frontend/src/app.html).
        web.addJavascriptInterface(new Object() {
            @android.webkit.JavascriptInterface
            public void onTheme(String dark) {
                boolean d = "1".equals(dark);
                getSharedPreferences(PREFS, MODE_PRIVATE).edit()
                        .putBoolean(PREF_DARK, d).apply();
                runOnUiThread(() -> applyTheme(d));
            }
        }, "SamvaraShell");

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);   // the app keeps its session in localStorage
        // Honor the page's <meta viewport> like a real mobile browser does.
        // Without these the page lays out at a legacy fixed width and the
        // right side of the app bar (New, theme toggle) is clipped off-screen.
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(true);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                Uri url = req.getUrl();
                // The app is a single page; anything leaving samvara.app is an
                // outbound link and belongs in the real browser.
                if ("samvara.app".equalsIgnoreCase(url.getHost())) return false;
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, url));
                } catch (Exception ignored) { }
                return true;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                harvestSession();
            }
        });

        if (savedInstanceState != null) {
            web.restoreState(savedInstanceState);
        } else {
            // Cold start: drop the HTTP cache so every open fetches the latest
            // deploy. WebView's cache heuristics otherwise serve a stale page
            // well past its max-age, defeating the "site deploy == app update"
            // premise. localStorage (the session) is untouched by this.
            web.clearCache(true);
            web.loadUrl(SITE);
        }

        requestNotificationPermission();
        scheduleDeadlinePoller();
    }

    /**
     * Copy the session token (and any API-base override from the in-app
     * Settings screen) out of the page's localStorage into app prefs, where
     * DeadlineJobService can reach them. Runs after every page load: the OTP
     * sign-in ends in a location.reload(), which lands here with the fresh
     * token; sign-out lands here with it gone.
     */
    private void harvestSession() {
        String js = "JSON.stringify({t:(function(){try{return localStorage.getItem('samvara.apiToken')||''}catch(e){return ''}})()," +
                "b:(function(){try{return localStorage.getItem('samvara.apiBaseUrl')||''}catch(e){return ''}})()})";
        web.evaluateJavascript(js, result -> {
            try {
                // evaluateJavascript returns a JSON-encoded string containing our JSON.
                String unquoted = (String) new JSONTokener(result).nextValue();
                JSONObject o = new JSONObject(unquoted);
                SharedPreferences.Editor e = getSharedPreferences(PREFS, MODE_PRIVATE).edit();
                e.putString(PREF_TOKEN, o.optString("t", ""));
                e.putString(PREF_API_BASE, o.optString("b", ""));
                e.apply();
            } catch (Exception ignored) { }
        });
    }

    /** Match the system-bar strip and icon contrast to the page theme. */
    private void applyTheme(boolean dark) {
        int bg = dark ? PAGE_BG_DARK : PAGE_BG_LIGHT;
        frame.setBackgroundColor(bg);
        web.setBackgroundColor(bg);   // covers the pre-paint flash too
        if (Build.VERSION.SDK_INT >= 30) {
            int lightIcons = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS
                    | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
            getWindow().getInsetsController()
                    .setSystemBarsAppearance(dark ? 0 : lightIcons, lightIcons);
        }
    }

    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                        != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1);
        }
    }

    private void scheduleDeadlinePoller() {
        // Never let the poller take the UI down with it. GrapheneOS's per-app
        // Network toggle revokes ACCESS_NETWORK_STATE at runtime, which makes
        // this schedule call throw SecurityException.
        try {
            JobScheduler js = getSystemService(JobScheduler.class);
            if (js.getPendingJob(JOB_ID) != null) return;
            js.schedule(new JobInfo.Builder(JOB_ID,
                    new ComponentName(this, DeadlineJobService.class))
                    .setPeriodic(POLL_INTERVAL_MS)
                    .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                    .setPersisted(true)   // survives reboots
                    .build());
        } catch (Exception ignored) {
            // WebView still works; deadline alerts just stay off until the
            // permission situation changes and the app is reopened.
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        web.saveState(outState);
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }
}
