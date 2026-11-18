package dev.finsec.s1;

public class MainActivity extends android.app.Activity {
    @Override public void onCreate(android.os.Bundle state) {
        super.onCreate(state);
        int units = getIntent().getIntExtra("qa_units", 7);
        android.widget.TextView view = new android.widget.TextView(this);
        view.setText(new ImportantLogic(10).classifyDemoUnits(units));
        setContentView(view);
    }
}
