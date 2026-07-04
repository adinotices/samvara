package app.samvara.shell;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.job.JobParameters;
import android.app.job.JobService;
import android.content.Intent;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;

/**
 * Every ~15 minutes: GET /v1/commitments and notify about anything that needs
 * a human before money moves. The web app can only warn you while it's open;
 * this is the tap on the shoulder that the 24h grace window otherwise lacks.
 *
 * Stages, at most one notification each per rung (deduped in prefs):
 *   due6    deadline within 6h on an active rung
 *   grace   deadline passed — the 24h confirmation window is running
 *   grace3  under 3h left in that window (last call before auto-charge)
 *   parked  auto-charged while unattended; awaiting a recommit
 *   auth    the stored session died (401) — polling is blind until sign-in
 */
public class DeadlineJobService extends JobService {

    private static final String CHANNEL = "deadlines";
    private static final String DEFAULT_API_BASE = "https://samvara-api.fly.dev";
    // Mirrors GRACE_MS in the web client and GRACE_HOURS on the server.
    private static final long GRACE_MS = 24 * 3600_000L;
    private static final long H = 3600_000L;

    @Override
    public boolean onStartJob(JobParameters params) {
        new Thread(() -> {
            try {
                check();
            } catch (Exception ignored) {
                // Transient network trouble; the next period retries.
            } finally {
                jobFinished(params, false);
            }
        }).start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return true; // reschedule if the system killed us mid-poll
    }

    private void check() throws Exception {
        SharedPreferences prefs = getSharedPreferences(MainActivity.PREFS, MODE_PRIVATE);
        String token = prefs.getString(MainActivity.PREF_TOKEN, "");
        if (token.isEmpty()) return; // not signed in yet; nothing to poll

        String base = prefs.getString(MainActivity.PREF_API_BASE, "");
        if (base.isEmpty()) base = DEFAULT_API_BASE;
        base = base.replaceAll("/+$", "").replaceAll("/v1$", "");

        HttpURLConnection conn = (HttpURLConnection) new URL(base + "/v1/commitments").openConnection();
        conn.setConnectTimeout(15000);
        conn.setReadTimeout(15000);
        conn.setRequestProperty("Authorization", "Bearer " + token);
        int status = conn.getResponseCode();
        if (status == 401) {
            // Dead session: without a token the poller is blind, which quietly
            // disarms the whole point of this app. Say so, once per session.
            notifyOnce(prefs, "auth|" + token.hashCode(), 9999,
                    "Signed out of Saṃvara",
                    "Deadline alerts are paused — open the app and sign in again.");
            return;
        }
        if (status != 200) return;

        String body;
        try (InputStream in = conn.getInputStream()) {
            body = new String(in.readAllBytes(), StandardCharsets.UTF_8);
        }
        JSONArray commitments = new JSONArray(body);
        long now = System.currentTimeMillis();
        Set<String> liveKeys = new HashSet<>();

        for (int i = 0; i < commitments.length(); i++) {
            JSONObject cm = commitments.getJSONObject(i);
            JSONObject r = cm.getJSONObject("current_rung");
            String id = cm.getString("id");
            String name = cm.getString("name");
            String rung = r.getString("start"); // rung identity for dedup
            int days = r.getInt("days");
            double stake = r.getDouble("stake");
            String stakeFmt = String.format(Locale.US, "$%.2f", stake);
            int notifyId = 100 + (id.hashCode() & 0x7fff);

            boolean resolved = r.optBoolean("completed") || r.optBoolean("awaiting_decision");
            boolean parked = r.optBoolean("awaiting_recommit") || r.optBoolean("auto_missed");
            long due = Instant.parse(r.getString("due")).toEpochMilli();
            long graceEnd = due + GRACE_MS;

            String prefix = id + "|" + rung + "|";
            if (parked) {
                double charged = r.optDouble("charged_amount", stake);
                liveKeys.add(prefix + "parked");
                notifyOnce(prefs, prefix + "parked", notifyId,
                        "Auto-charged " + String.format(Locale.US, "$%.2f", charged),
                        "'" + name + "' hit the end of its grace window. Recommit when you're ready.");
            } else if (!resolved && now >= due && now < graceEnd) {
                long hoursLeft = Math.max(1, (graceEnd - now) / H);
                liveKeys.add(prefix + "grace");
                liveKeys.add(prefix + "grace3");
                notifyOnce(prefs, prefix + "grace", notifyId,
                        "Deadline reached: " + name,
                        "Confirm within " + hoursLeft + "h — no response means a "
                                + stakeFmt + " charge.");
                if (graceEnd - now < 3 * H) {
                    notifyOnce(prefs, prefix + "grace3", notifyId,
                            "Last call: " + name,
                            "Under " + hoursLeft + "h to respond before the "
                                    + stakeFmt + " auto-charge.");
                }
            } else if (!resolved && now < due) {
                liveKeys.add(prefix + "due6");
                if (due - now < 6 * H) {
                    long hoursLeft = Math.max(1, (due - now) / H);
                    notifyOnce(prefs, prefix + "due6", notifyId,
                            "Deadline in ~" + hoursLeft + "h: " + name,
                            days + "-day rung, " + stakeFmt + " at stake. Finish clean.");
                }
            }
        }

        // Drop dedup keys for rungs that no longer exist so the set stays small.
        Set<String> fired = new HashSet<>(prefs.getStringSet("fired", new HashSet<>()));
        fired.retainAll(liveKeys);
        prefs.edit().putStringSet("fired", fired).apply();
    }

    /** Post the notification unless this exact key already fired. */
    private void notifyOnce(SharedPreferences prefs, String key, int notifyId,
                            String title, String text) {
        Set<String> fired = new HashSet<>(prefs.getStringSet("fired", new HashSet<>()));
        if (fired.contains(key)) return;
        fired.add(key);
        prefs.edit().putStringSet("fired", fired).apply();

        NotificationManager nm = getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel(
                CHANNEL, "Deadlines", NotificationManager.IMPORTANCE_HIGH));

        PendingIntent open = PendingIntent.getActivity(this, 0,
                new Intent(this, MainActivity.class),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        nm.notify(notifyId, new Notification.Builder(this, CHANNEL)
                .setSmallIcon(R.drawable.ic_bars)
                .setContentTitle(title)
                .setContentText(text)
                .setStyle(new Notification.BigTextStyle().bigText(text))
                .setContentIntent(open)
                .setAutoCancel(true)
                .build());
    }
}
