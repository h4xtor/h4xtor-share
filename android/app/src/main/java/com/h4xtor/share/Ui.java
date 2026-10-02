package com.h4xtor.share;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.res.ColorStateList;
import android.content.res.Configuration;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.net.Uri;
import android.text.TextUtils;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.Switch;
import android.widget.TextView;

import java.util.Locale;

/** Tiny design system: one palette (light + dark), rounded surfaces, typography. */
public final class Ui {
    public static final int ACCENT_LIGHT = Color.parseColor("#C96442");

    public final Context context;
    public final boolean dark;
    public final int bg;
    public final int surface;
    public final int surfaceAlt;
    public final int border;
    public final int text;
    public final int muted;
    public final int faint;
    public final int accent;
    public final int accentPressed;
    public final int accentSoft;
    public final int onAccent;
    public final int success;
    public final int successSoft;
    public final int warning;
    public final int warningSoft;
    public final int danger;
    public final int dangerSoft;
    public final int neutralSoft;
    public final int track;
    private final float density;

    public Ui(Context context) {
        this.context = context;
        int mode = context.getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK;
        dark = mode == Configuration.UI_MODE_NIGHT_YES;
        density = context.getResources().getDisplayMetrics().density;
        if (dark) {
            bg = Color.parseColor("#1E1D1B");
            surface = Color.parseColor("#282725");
            surfaceAlt = Color.parseColor("#302F2C");
            border = Color.parseColor("#383632");
            text = Color.parseColor("#F3F1EA");
            muted = Color.parseColor("#A8A397");
            faint = Color.parseColor("#77736A");
            accent = Color.parseColor("#D97757");
            accentPressed = Color.parseColor("#E48B6D");
            accentSoft = Color.parseColor("#3D2C24");
            success = Color.parseColor("#4CC38A");
            successSoft = Color.parseColor("#1F3529");
            warning = Color.parseColor("#E2A84B");
            warningSoft = Color.parseColor("#3A2F1C");
            danger = Color.parseColor("#EF6B55");
            dangerSoft = Color.parseColor("#3E2420");
            neutralSoft = Color.parseColor("#33312D");
            track = Color.parseColor("#3A3834");
        } else {
            bg = Color.parseColor("#FAF9F5");
            surface = Color.parseColor("#FFFFFF");
            surfaceAlt = Color.parseColor("#F4F2EC");
            border = Color.parseColor("#E6E2D6");
            text = Color.parseColor("#1F1E1D");
            muted = Color.parseColor("#6F6B62");
            faint = Color.parseColor("#A49F94");
            accent = ACCENT_LIGHT;
            accentPressed = Color.parseColor("#B4553A");
            accentSoft = Color.parseColor("#F7E8E0");
            success = Color.parseColor("#2E8B57");
            successSoft = Color.parseColor("#E3F2E9");
            warning = Color.parseColor("#B7791F");
            warningSoft = Color.parseColor("#FBF0DC");
            danger = Color.parseColor("#C2412D");
            dangerSoft = Color.parseColor("#FBE5E1");
            neutralSoft = Color.parseColor("#EFECE4");
            track = Color.parseColor("#ECE8DE");
        }
        onAccent = Color.WHITE;
    }

    /** Edge-to-edge window with transparent system bars and correctly tinted icons. */
    @SuppressWarnings("deprecation")
    public void styleWindow(Activity activity) {
        android.view.Window window = activity.getWindow();
        window.setStatusBarColor(Color.TRANSPARENT);
        window.setNavigationBarColor(Color.TRANSPARENT);
        if (android.os.Build.VERSION.SDK_INT >= 29) {
            window.setNavigationBarContrastEnforced(false);
        }
        View decor = window.getDecorView();
        int flags = View.SYSTEM_UI_FLAG_LAYOUT_STABLE | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION;
        if (!dark) {
            flags |= View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
        }
        decor.setSystemUiVisibility(flags);
    }

    /** Calls {@code consumer} with the top and bottom system-bar insets whenever they change. */
    @SuppressWarnings("deprecation")
    public static void onInsets(View root, InsetsConsumer consumer) {
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            consumer.apply(insets.getSystemWindowInsetTop(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        root.requestApplyInsets();
    }

    public interface InsetsConsumer {
        void apply(int top, int bottom);
    }

    public int dp(float value) {
        return Math.round(value * density);
    }

    public GradientDrawable rounded(int fill, int stroke, float radiusDp) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(fill);
        drawable.setCornerRadius(dp(radiusDp));
        if (stroke != 0) {
            drawable.setStroke(Math.max(1, dp(1)), stroke);
        }
        return drawable;
    }

    public Drawable ripple(Drawable content, float radiusDp) {
        GradientDrawable mask = new GradientDrawable();
        mask.setColor(Color.WHITE);
        mask.setCornerRadius(dp(radiusDp));
        int rippleColor = dark ? Color.argb(40, 255, 255, 255) : Color.argb(28, 0, 0, 0);
        return new RippleDrawable(ColorStateList.valueOf(rippleColor), content, mask);
    }

    public TextView text(String value, float sizeSp, int color, boolean bold) {
        TextView view = new TextView(context);
        view.setText(value);
        view.setTextSize(TypedValue.COMPLEX_UNIT_SP, sizeSp);
        view.setTextColor(color);
        view.setTypeface(Typeface.create("sans-serif" + (bold ? "-medium" : ""), Typeface.NORMAL));
        view.setIncludeFontPadding(true);
        return view;
    }

    public TextView title(String value, float sizeSp) {
        TextView view = text(value, sizeSp, text, true);
        view.setTypeface(Typeface.create("sans-serif-medium", Typeface.BOLD));
        view.setLetterSpacing(-0.01f);
        return view;
    }

    public TextView label(String value) {
        TextView view = text(value.toUpperCase(Locale.ROOT), 11.5f, faint, true);
        view.setLetterSpacing(0.08f);
        return view;
    }

    /** kind: primary | secondary | ghost | soft | danger */
    public TextView button(String label, String kind) {
        TextView view = text(label, 14.5f, text, true);
        view.setGravity(Gravity.CENTER);
        view.setSingleLine(true);
        view.setEllipsize(TextUtils.TruncateAt.END);
        view.setPadding(dp(16), 0, dp(16), 0);
        view.setMinHeight(dp(46));
        view.setClickable(true);
        view.setFocusable(true);
        int fill;
        int stroke = 0;
        int color;
        switch (kind) {
            case "primary":
                fill = accent;
                color = onAccent;
                break;
            case "soft":
                fill = accentSoft;
                color = accent;
                break;
            case "ghost":
                fill = Color.TRANSPARENT;
                color = text;
                break;
            case "danger":
                fill = dangerSoft;
                color = danger;
                break;
            default:
                fill = surface;
                stroke = border;
                color = text;
        }
        view.setTextColor(color);
        view.setBackground(ripple(rounded(fill, stroke, 14), 14));
        return view;
    }

    public LinearLayout card() {
        LinearLayout layout = new LinearLayout(context);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(dp(18), dp(16), dp(18), dp(16));
        layout.setBackground(rounded(surface, border, 20));
        return layout;
    }

    public LinearLayout row() {
        LinearLayout layout = new LinearLayout(context);
        layout.setOrientation(LinearLayout.HORIZONTAL);
        layout.setGravity(Gravity.CENTER_VERTICAL);
        return layout;
    }

    public LinearLayout column() {
        LinearLayout layout = new LinearLayout(context);
        layout.setOrientation(LinearLayout.VERTICAL);
        return layout;
    }

    public TextView pill(String value, String tone) {
        TextView view = text(value, 12f, muted, true);
        int fill;
        int color;
        switch (tone) {
            case "success": fill = successSoft; color = success; break;
            case "warning": fill = warningSoft; color = warning; break;
            case "danger": fill = dangerSoft; color = danger; break;
            case "accent": fill = accentSoft; color = accent; break;
            default: fill = neutralSoft; color = muted;
        }
        view.setTextColor(color);
        view.setPadding(dp(10), dp(4), dp(10), dp(4));
        view.setBackground(rounded(fill, 0, 999));
        return view;
    }

    public TextView avatar(String platform, int sizeDp) {
        String key = platform == null ? "" : platform.toLowerCase(Locale.ROOT);
        int color;
        String letter;
        switch (key) {
            case "android": color = Color.parseColor("#3DDC84"); letter = "A"; break;
            case "windows": color = Color.parseColor("#2F7BEA"); letter = "W"; break;
            case "linux": color = Color.parseColor("#E8A33D"); letter = "L"; break;
            case "darwin":
            case "macos": color = Color.parseColor("#8E8E93"); letter = "M"; break;
            default: color = faint; letter = "?";
        }
        TextView view = text(letter, sizeDp * 0.38f, Color.WHITE, true);
        view.setGravity(Gravity.CENTER);
        GradientDrawable circle = new GradientDrawable();
        circle.setShape(GradientDrawable.OVAL);
        circle.setColor(color);
        view.setBackground(circle);
        view.setLayoutParams(new LinearLayout.LayoutParams(dp(sizeDp), dp(sizeDp)));
        return view;
    }

    public android.widget.ImageView icon(int drawable, int color, int sizeDp) {
        android.widget.ImageView view = new android.widget.ImageView(context);
        view.setImageResource(drawable);
        view.setImageTintList(ColorStateList.valueOf(color));
        view.setLayoutParams(new LinearLayout.LayoutParams(dp(sizeDp), dp(sizeDp)));
        return view;
    }

    /** Rounded soft-accent square with an icon in the middle. */
    public android.widget.FrameLayout iconBadge(int drawable, int sizeDp, int fill, int color) {
        android.widget.FrameLayout frame = new android.widget.FrameLayout(context);
        frame.setBackground(rounded(fill, 0, sizeDp * 0.3f));
        android.widget.ImageView image = icon(drawable, color, Math.round(sizeDp * 0.5f));
        android.widget.FrameLayout.LayoutParams params = new android.widget.FrameLayout.LayoutParams(
                dp(sizeDp * 0.5f), dp(sizeDp * 0.5f), Gravity.CENTER);
        frame.addView(image, params);
        frame.setLayoutParams(new LinearLayout.LayoutParams(dp(sizeDp), dp(sizeDp)));
        return frame;
    }

    public TextView iconTile(String glyph, int sizeDp) {
        TextView view = text(glyph, sizeDp * 0.42f, accent, true);
        view.setGravity(Gravity.CENTER);
        view.setBackground(rounded(accentSoft, 0, sizeDp * 0.32f));
        view.setLayoutParams(new LinearLayout.LayoutParams(dp(sizeDp), dp(sizeDp)));
        return view;
    }

    public Switch toggle(boolean checked) {
        Switch view = new Switch(context);
        view.setChecked(checked);
        int[][] states = {{android.R.attr.state_checked}, {}};
        view.setThumbTintList(new ColorStateList(states, new int[]{Color.WHITE, dark ? faint : Color.WHITE}));
        view.setTrackTintList(new ColorStateList(states, new int[]{accent, track}));
        view.setTrackTintMode(android.graphics.PorterDuff.Mode.SRC);
        return view;
    }

    public ProgressBar progress() {
        ProgressBar bar = new ProgressBar(context, null, android.R.attr.progressBarStyleHorizontal);
        bar.setMax(1000);
        bar.setProgressTintList(ColorStateList.valueOf(accent));
        bar.setProgressBackgroundTintList(ColorStateList.valueOf(track));
        bar.setLayoutParams(new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(6)));
        return bar;
    }

    public View divider() {
        View view = new View(context);
        view.setBackgroundColor(border);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, Math.max(1, dp(1)));
        params.setMargins(0, dp(12), 0, dp(12));
        view.setLayoutParams(params);
        return view;
    }

    public View space(int heightDp) {
        View view = new View(context);
        view.setLayoutParams(new LinearLayout.LayoutParams(1, dp(heightDp)));
        return view;
    }

    public LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
    }

    public LinearLayout.LayoutParams margins(int left, int top, int right, int bottom) {
        LinearLayout.LayoutParams params = matchWrap();
        params.setMargins(dp(left), dp(top), dp(right), dp(bottom));
        return params;
    }

    public LinearLayout.LayoutParams weight(float weight) {
        return new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, weight);
    }

    // ----------------------------------------------------------------- helpers
    public static String formatBytes(long value) {
        double size = Math.max(0, value);
        String[] units = {"B", "KB", "MB", "GB", "TB"};
        int unit = 0;
        while (size >= 1024 && unit < units.length - 1) {
            size /= 1024;
            unit++;
        }
        return unit == 0
                ? String.format(Locale.ROOT, "%d B", (long) size)
                : String.format(Locale.ROOT, "%.1f %s", size, units[unit]);
    }

    public static String formatEta(double seconds) {
        if (seconds < 1 || seconds > 172_800) {
            return "";
        }
        long total = (long) seconds;
        if (total < 60) {
            return total + " s tilbage";
        }
        long minutes = total / 60;
        if (minutes < 60) {
            return minutes + " min " + (total % 60) + " s tilbage";
        }
        return (minutes / 60) + " t " + (minutes % 60) + " min tilbage";
    }

    public static boolean isLink(String text) {
        if (text == null) {
            return false;
        }
        String value = text.trim();
        if (value.contains(" ") || value.contains("\n")) {
            return false;
        }
        String lower = value.toLowerCase(Locale.ROOT);
        return lower.startsWith("http://") || lower.startsWith("https://");
    }

    public static Intent openFileIntent(Uri uri, String fileName) {
        Intent intent = new Intent(Intent.ACTION_VIEW);
        intent.setDataAndType(uri, H4xtorServer.mimeFor(fileName));
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
        return intent;
    }

    public static String platformLabel(String platform) {
        switch (platform == null ? "" : platform.toLowerCase(Locale.ROOT)) {
            case "android": return "Android";
            case "windows": return "Windows";
            case "linux": return "Linux";
            case "darwin":
            case "macos": return "macOS";
            default: return "Enhed";
        }
    }
}
