package dev.finsec.poc;

import android.app.Activity;
import android.os.Bundle;
import android.graphics.Color;
import android.view.View;
import android.view.WindowManager;
import android.view.inputmethod.InputMethodManager;
import android.content.Context;
import android.widget.*;

/** Offline synthetic fixture. No network permission, real accounts, or transactions. */
public final class MainActivity extends Activity {
    private LinearLayout body;
    private String state = "login", recipient = "", amount = "";
    private boolean secure = false;
    private int confirmations = 0;
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        android.content.SharedPreferences prefs = getPreferences(MODE_PRIVATE);
        state = prefs.getString("state", "login"); secure = prefs.getBoolean("secure", false);
        recipient = prefs.getString("recipient", ""); amount = prefs.getString("amount", "");
        confirmations = prefs.getInt("confirmations", 0);
        if (saved != null) {
            state = saved.getString("state", "login"); secure = saved.getBoolean("secure");
            recipient = saved.getString("recipient", ""); amount = saved.getString("amount", "");
            confirmations = saved.getInt("confirmations");
        }
        render();
    }
    @Override public void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        out.putString("state", state); out.putBoolean("secure", secure);
        out.putString("recipient", recipient); out.putString("amount", amount);
        out.putInt("confirmations", confirmations);
    }
    private TextView label(int id, String value) {
        TextView v = new TextView(this); v.setId(id); v.setText(value); v.setTextSize(18);
        v.setPadding(0, 8, 0, 8); body.addView(v); return v;
    }
    private EditText field(int id, String hint, String value, int inputType) {
        label(View.NO_ID, hint);
        EditText v = new EditText(this); v.setId(id); v.setSingleLine(true);
        v.setInputType(inputType); v.setText(value); body.addView(v); return v;
    }
    private void button(int id, String title, Runnable action) {
        Button v = new Button(this); v.setId(id); v.setText(title); body.addView(v);
        v.setOnClickListener(w -> action.run());
    }
    private void go(String next) {
        View focus = getCurrentFocus();
        if (focus != null) ((InputMethodManager)getSystemService(Context.INPUT_METHOD_SERVICE))
            .hideSoftInputFromWindow(focus.getWindowToken(), 0);
        state = next; render();
    }
    private void render() {
        getPreferences(MODE_PRIVATE).edit().putString("state", state).putBoolean("secure", secure)
            .putString("recipient", recipient).putString("amount", amount).putInt("confirmations", confirmations).commit();
        if (secure) getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        else getWindow().clearFlags(WindowManager.LayoutParams.FLAG_SECURE);
        ScrollView scroll = new ScrollView(this);
        body = new LinearLayout(this); body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(24, 16, 24, 16); body.setBackgroundColor(Color.WHITE);
        scroll.addView(body); setContentView(scroll);
        label(View.NO_ID, "SYNTHETIC QA · NO REAL MONEY");
        label(R.id.screen_state, state);
        label(R.id.secure_state, secure ? "secure:on" : "secure:off");
        button(R.id.secure_toggle, "Toggle FLAG_SECURE (manual, outside recording)", () -> { secure = !secure; render(); });
        button(R.id.reset, "RESET synthetic state (manual)", () -> {
            recipient = ""; amount = ""; confirmations = 0; go("login");
        });
        if (state.equals("login")) {
            label(R.id.initial_state, "reset:" + confirmations + ":" + recipient + ":" + amount);
            EditText user = field(R.id.username, "qa-user", "", 1);
            EditText pass = field(R.id.password, "qa-pass (public fixture)", "", 1);
            button(R.id.login, "Synthetic login", () -> {
                if (user.getText().toString().equals("qa-user") && pass.getText().toString().equals("qa-pass")) go("menu");
                else Toast.makeText(this, "Use public qa-user / qa-pass", Toast.LENGTH_SHORT).show();
            });
        } else if (state.equals("menu")) {
            button(R.id.transfer, "Mock transfer", () -> go("transfer"));
        } else if (state.equals("transfer")) {
            EditText to = field(R.id.recipient, "DEMO-001", recipient, 1);
            EditText sum = field(R.id.amount, "1000", amount, 2);
            button(R.id.review, "Review synthetic input", () -> {
                recipient = to.getText().toString(); amount = sum.getText().toString();
                if (recipient.equals("DEMO-001") && amount.equals("1000")) go("review");
                else Toast.makeText(this, "Use DEMO-001 and 1000 only", Toast.LENGTH_SHORT).show();
            });
        } else if (state.equals("review")) {
            label(View.NO_ID, "DEMO-001 · 1000 synthetic units");
            button(R.id.confirm, "Confirm simulation", () -> { confirmations++; go("confirmed"); });
        } else {
            label(R.id.receipt, "SIMULATED:" + confirmations + ":" + recipient + ":" + amount);
        }
    }
    @Override public void onBackPressed() {
        if (state.equals("review")) go("transfer");
        else if (state.equals("transfer")) go("menu");
        else if (state.equals("menu")) go("login");
        else if (state.equals("confirmed")) go("menu");
        else super.onBackPressed();
    }
}
