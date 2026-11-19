package dev.finsec.qa.stateonly;

import android.app.Activity;
import android.os.Bundle;
import android.widget.Button;

public final class StateActivity extends Activity {
    Button button;
    String state = "QA_READY";
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        button = new Button(this);
        button.setText("Synthetic QA action");
        button.setOnClickListener(v -> { state = "QA_SENT"; button.setText("Synthetic action complete"); });
        setContentView(button);
    }
}
