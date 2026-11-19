package dev.finsec.qa.stateonly;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Intent;
import android.os.Bundle;

/** Fixed test of our own activity; accepts no command, selector or input arguments. */
public final class StateProbe extends Instrumentation {
    @Override public void onCreate(Bundle args) { super.onCreate(args); start(); }
    @Override public void onStart() {
        StateActivity activity = null;
        Bundle result = new Bundle();
        int code = Activity.RESULT_CANCELED;
        try {
            Intent intent = new Intent(getTargetContext(), StateActivity.class);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            activity = (StateActivity) startActivitySync(intent);
            final StateActivity target = activity;
            final boolean[] valid = {false};
            runOnMainSync(() -> {
                valid[0] = "QA_READY".equals(target.state) && target.button.performClick()
                        && "QA_SENT".equals(target.state);
            });
            waitForIdleSync();
            if (valid[0]) {
                result.putString("qa_contract", "state-only.v1");
                result.putString("qa_states", "QA_READY>QA_SENT");
                code = Activity.RESULT_OK;
            }
        } catch (Exception ignored) {
            // No exception text, UI tree, input data or network output is exported.
        } finally {
            if (activity != null) {
                final StateActivity target = activity;
                runOnMainSync(target::finish);
                waitForIdleSync();
            }
            finish(code, result);
        }
    }
}
