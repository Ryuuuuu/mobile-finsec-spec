package dev.finsec.qa.standalone;

import android.app.Activity;
import android.os.Bundle;
import android.view.WindowManager;
import android.view.inputmethod.InputMethodManager;
import android.content.Context;
import android.widget.*;

/** Disposable offline UI, separate package/storage; no account or network permission. */
public final class EntryActivity extends Activity {
    private String stage="ready", draft="";
    private boolean secure=false;
    private LinearLayout body;
    @Override public void onCreate(Bundle saved) {super.onCreate(saved);render();}
    private void button(int id,String title,Runnable action) {
        Button b=new Button(this);b.setId(id);b.setText(title);body.addView(b);
        b.setOnClickListener(v->action.run());
    }
    private void hideKeyboard() {
        if(getCurrentFocus()!=null)((InputMethodManager)getSystemService(Context.INPUT_METHOD_SERVICE))
            .hideSoftInputFromWindow(getCurrentFocus().getWindowToken(),0);
    }
    private void render() {
        if(secure)getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        else getWindow().clearFlags(WindowManager.LayoutParams.FLAG_SECURE);
        body=new LinearLayout(this);body.setOrientation(LinearLayout.VERTICAL);body.setPadding(24,24,24,24);
        body.setBackgroundColor(android.graphics.Color.WHITE);setContentView(body);
        TextView title=new TextView(this);title.setText("DISPOSABLE OFFLINE QA - NO REAL DATA");body.addView(title);
        TextView status=new TextView(this);status.setId(R.id.state);status.setText(stage);status.setTextSize(24);body.addView(status);
        button(R.id.reset,"RESET disposable state",()->{hideKeyboard();stage="ready";draft="";render();});
        button(R.id.secure,secure?"Capture protection ON":"Capture protection OFF",()->{secure=!secure;render();});
        if(getPackageName().endsWith(".canvas")) {
            android.view.View canvas=new android.view.View(this) {
                @Override protected void onDraw(android.graphics.Canvas c) {
                    android.graphics.Paint paint=new android.graphics.Paint();paint.setColor(android.graphics.Color.rgb(30,90,150));
                    c.drawRect(0,0,getWidth(),getHeight(),paint);paint.setColor(android.graphics.Color.WHITE);paint.setTextSize(36);
                    c.drawText("Canvas: tap to advance "+stage,20,100,paint);
                }
                @Override public boolean onTouchEvent(android.view.MotionEvent event) {
                    if(event.getAction()==android.view.MotionEvent.ACTION_UP) {
                        stage=stage.equals("ready")?"review":stage.equals("review")?"done":"ready";render();
                    }
                    return true;
                }
            };
            body.addView(canvas,new LinearLayout.LayoutParams(-1,400));return;
        }
        if(stage.equals("ready")) {
            EditText input=new EditText(this);input.setId(R.id.draft);input.setSingleLine(true);input.setText(draft);input.setHint("Non-secret QA draft");body.addView(input);
            button(R.id.next,"Review draft",()->{draft=input.getText().toString();hideKeyboard();stage="review";render();});
            EditText password=new EditText(this);password.setId(R.id.secret);password.setSingleLine(true);password.setInputType(129);password.setHint("Password rejection test - leave empty");body.addView(password);
        } else if(stage.equals("review")) {
            TextView value=new TextView(this);value.setText(draft);body.addView(value);
            button(R.id.confirm,"Confirm local draft (no transaction)",()->{stage="done";render();});
        }
    }
    @Override public void onBackPressed(){hideKeyboard();stage="ready";draft="";render();}
}
