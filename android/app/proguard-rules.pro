# ProGuard/R8 rules for Samvara Android app.
# The app uses framework APIs only; these rules preserve the WebView bridge
# and notification APIs that DeadlineJobService depends on.

# Keep all framework APIs used by the app.
-keep class android.webkit.WebView { *; }
-keep class android.webkit.WebViewClient { *; }
-keep class android.webkit.WebSettings { *; }
-keep class android.webkit.JavascriptInterface { *; }
-keepclassmembers class android.webkit.** {
    public *;
}

# Preserve JobService and related classes.
-keep class android.app.job.JobService { *; }
-keep class android.app.job.JobInfo { *; }
-keep class android.app.job.JobParameters { *; }
-keep class android.app.job.JobScheduler { *; }
-keepclassmembers class android.app.job.** {
    public *;
}

# Preserve notification APIs.
-keep class android.app.Notification { *; }
-keep class android.app.NotificationChannel { *; }
-keep class android.app.NotificationManager { *; }
-keep class android.app.PendingIntent { *; }
-keepclassmembers class android.app.** {
    public *;
}

# Preserve SharedPreferences APIs.
-keep class android.content.SharedPreferences { *; }
-keepclassmembers class android.content.SharedPreferences** {
    public *;
}

# Preserve org.json APIs used by the app.
-keep class org.json.** { *; }
-keepclassmembers class org.json.** {
    public *;
}

# Keep activity and service classes.
-keep public class app.samvara.shell.** extends android.app.Activity
-keep public class app.samvara.shell.** extends android.app.job.JobService
-keepclassmembers class app.samvara.shell.** {
    public *;
    *** onTheme(...);
}

# Keep native method names.
-keepclasseswithmembernames class * {
    native <methods>;
}

# Preserve line numbers for better crash reports.
-keepattributes SourceFile,LineNumberTable

# Keep exception information.
-keepattributes Exceptions

# Preserve annotations used by the framework.
-keepattributes *Annotation*,InnerClasses

# Suppress warnings about missing classes that are optional or framework-provided.
-dontwarn android.**
-dontwarn androidx.**
