// SPDX-License-Identifier: Apache-2.0
package org.gkdpixel2.gpu;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.net.LocalSocket;
import android.net.LocalSocketAddress;
import android.net.Uri;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.os.PowerManager;
import android.widget.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONObject;

public final class DriverActivity extends Activity {
    private final ExecutorService work = Executors.newSingleThreadExecutor();
    private LinearLayout actions;
    private TextView current, detail;
    private boolean busy, picking;
    private static final int PICK = 4, READY = 33, TRIAL = 34, KEPT = 35, TRYING = 36, STARTING = 37;

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        setTitle(R.string.title);
        ScrollView scroll = new ScrollView(this);
        LinearLayout body = new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        int p = Math.round(14 * getResources().getDisplayMetrics().density);
        body.setPadding(p, p, p, p);
        scroll.addView(body);
        current = new TextView(this); current.setTextSize(20); body.addView(current);
        detail = new TextView(this); detail.setPadding(0,p/2,0,p); body.addView(detail);
        actions = new LinearLayout(this); actions.setOrientation(LinearLayout.VERTICAL); body.addView(actions);
        setContentView(scroll);
        if (saved != null) picking = saved.getBoolean("picking");
    }
    @Override public void onSaveInstanceState(Bundle out) {super.onSaveInstanceState(out);out.putBoolean("picking",picking);}
    @Override public void onResume() {super.onResume();if (!busy && !picking) request('S', null, false);}
    @Override public void onDestroy() {work.shutdown();super.onDestroy();}
    private void button(int title, Runnable click) {
        Button b = new Button(this); b.setText(title); b.setAllCaps(false);b.setOnClickListener(v -> click.run());actions.addView(b);
    }
    private void ask(char action,int text) {
        new AlertDialog.Builder(this).setMessage(text).setNegativeButton(R.string.cancel,null)
            .setPositiveButton(action == 'T' ? R.string.powerOff : R.string.reboot,
                (d,w)->request(action,null,true)).show();
    }
    private void pick() {
        picking=true;
        Intent i=new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*");
        try {startActivityForResult(i,PICK);} catch (RuntimeException e) {picking=false;showError(R.string.file);}
    }
    @Override protected void onActivityResult(int code,int result,Intent data) {
        super.onActivityResult(code,result,data);
        if (code!=PICK) return;
        picking=false;
        if (result==RESULT_OK && data!=null && data.getData()!=null) request('I',data.getData(),false);
    }
    private JSONObject transact(char op,Uri uri) throws Exception {
        try(LocalSocket s=new LocalSocket();
            ParcelFileDescriptor p=uri==null?null:getContentResolver().openFileDescriptor(uri,"r")) {
            if(uri!=null && p==null) throw new FileNotFoundException();
            s.connect(new LocalSocketAddress("pixel2_gpu",LocalSocketAddress.Namespace.RESERVED));
            s.setSoTimeout(240000);
            if(p!=null)s.setFileDescriptorsForSend(new FileDescriptor[]{p.getFileDescriptor()});
            s.getOutputStream().write((int)op);
            s.setFileDescriptorsForSend(null);
            BufferedReader reader=new BufferedReader(new InputStreamReader(s.getInputStream(),StandardCharsets.UTF_8));
            String line=reader.readLine();if(line==null||line.length()>1024)throw new IOException();
            return new JSONObject(line);
        }
    }
    private void request(char op,Uri uri,boolean applyNextBoot) {
        if(busy)return;
        busy=true;actions.removeAllViews();detail.setText(op=='I'?R.string.busy:R.string.loading);
        work.execute(()->{
            JSONObject response=null;int problem=0;
            try{response=transact(op,uri);}catch(Exception e){problem=op=='I'?R.string.file:R.string.board;}
            final int err=problem;final JSONObject result=response;
            runOnUiThread(()->{
                if(isDestroyed()||isFinishing())return;
                busy=false;
                if(err!=0){showError(err);return;}
                if(!result.optBoolean("ok")){
                    String why=result.optString("error");
                    showError("file".equals(why)?R.string.file:"integrity".equals(why)?R.string.integrity:
                        "board".equals(why)?R.string.board:("state".equals(why)||"mounted".equals(why))?R.string.state:R.string.io);return;
                }
                render(result);
                if (applyNextBoot) applySelection(op);
            });
        });
    }
    private void applySelection(char action) {
        boolean trial = action == 'T';
        try {
            if (trial) {
                Intent powerOff = new Intent("com.android.internal.intent.action.REQUEST_SHUTDOWN");
                powerOff.setClassName("android", "com.android.internal.app.ShutdownActivity");
                powerOff.putExtra("android.intent.extra.USER_REQUESTED_SHUTDOWN", true);
                startActivity(powerOff);
            } else {
                getSystemService(PowerManager.class).reboot(null);
            }
        } catch (RuntimeException e) {
            detail.setText(trial ? R.string.manualShutdown : R.string.manual);
        }
    }
    private void showError(int message) {
        detail.setText(message);actions.removeAllViews();button(R.string.retry,()->request('S',null,false));
        actions.getChildAt(0).requestFocus();
    }
    private void render(JSONObject j) {
        String mode=j.optString("active");long state=j.optLong("state",-1);
        boolean forced="forced".equals(mode), mesa=forced||"mesa".equals(mode), installed=state>=READY&&state<=STARTING;
        current.setText(getString(R.string.current,getString(mesa?R.string.mesa:R.string.mali)));
        int description=R.string.empty;actions.removeAllViews();
        if(mesa){
            if(forced)description=R.string.forced;
            else if(state==TRIAL || state==KEPT)description=R.string.queued;
            else if(state==TRYING || state==STARTING)description=R.string.fallback;
            else if(state==READY)description=R.string.ready;
            else if(state!=32)description=R.string.broken;
            if(installed&&!forced)button(R.string.use,()->ask('T',R.string.tryBody));
            if(installed&&state!=READY)button(R.string.restore,()->request('M',null,false));
            button(R.string.pick,this::pick);
        } else {
            description=state==READY?R.string.queued:state==TRYING?R.string.trial:R.string.kept;
            if(state==TRYING && "trial".equals(mode))button(R.string.keep,()->request('K',null,false));
            button(R.string.restartMesa,()->ask('M',R.string.mesaBody));
        }
        detail.setText(description);if(actions.getChildCount()>0)actions.getChildAt(0).requestFocus();
    }
}
