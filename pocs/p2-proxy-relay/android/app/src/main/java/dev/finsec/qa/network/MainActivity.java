package dev.finsec.qa.network;

import android.app.Activity;
import android.os.Bundle;
import android.widget.TextView;
import android.widget.Button;
import android.widget.LinearLayout;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceError;
import org.json.JSONObject;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.security.cert.CertificateFactory;
import javax.net.ssl.*;

/** Disposable fixture: fixed IPv4 loopback, synthetic bytes only, no arbitrary URL. */
public class MainActivity extends Activity {
    private TextView status;
    private boolean interactive=false;
    private int count=0;
    private Button nativeButton,webButton;
    private WebView web;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        status=new TextView(this);status.setTextSize(20);status.setPadding(32,64,32,32);
        status.setText("P2 DISPOSABLE NETWORK QA\nNo real data. Loopback only.\nAwait explicit test invocation.");setContentView(status);
        String protocol=getIntent().getStringExtra("protocol");
        String token=getIntent().getStringExtra("token");
        int port=getIntent().getIntExtra("port",0);
        if(protocol==null)return;
        if(!protocol.matches("http|https|ws|wss") || token==null || !token.matches("qa-[a-z0-9-]{1,60}") || port<1024 || port>65535) {
            status.setText("Rejected invalid fixture arguments");return;
        }
        if(getIntent().getBooleanExtra("interactive",false)) {
            if(!protocol.equals("http")){status.setText("Interactive fixture supports HTTP only");return;}
            interactive=true;LinearLayout layout=new LinearLayout(this);layout.setOrientation(LinearLayout.VERTICAL);layout.setPadding(24,64,24,24);
            TextView title=new TextView(this);title.setText("P1 + P2 DISPOSABLE QA / LOOPBACK ONLY");layout.addView(title);
            ((android.view.ViewGroup)status.getParent()).removeView(status);
            status.setId(R.id.state);status.setText("ready");layout.addView(status,new LinearLayout.LayoutParams(-1,-2));
            nativeButton=new Button(this);nativeButton.setId(R.id.send_native);nativeButton.setText("SEND NATIVE HTTP");layout.addView(nativeButton);
            webButton=new Button(this);webButton.setId(R.id.send_webview);webButton.setText("SEND WEBVIEW HTTP");layout.addView(webButton);
            web=new WebView(this);web.getSettings().setJavaScriptEnabled(true);layout.addView(web,new LinearLayout.LayoutParams(-1,200));setContentView(layout);
            nativeButton.setOnClickListener(v->{int n=++count;busy();new Thread(()->run(protocol,port,token+"-native-"+n),"p2-fixture").start();});
            webButton.setOnClickListener(v->{int n=++count;busy();String id=token+"-webview-"+n;
                web.setWebViewClient(new WebViewClient(){
                    @Override public void onReceivedError(WebView view,WebResourceRequest req,WebResourceError error){if(req.isForMainFrame())finishWeb(id,false);}
                    @Override public void onPageFinished(WebView view,String url){if(url.equals("http://127.0.0.1:"+port+"/synthetic/"+id))view.evaluateJavascript("document.body.innerText",value->finishWeb(id,value.equals(JSONObject.quote(id))));}
                });
                web.loadUrl("http://127.0.0.1:"+port+"/synthetic/"+id);
            });return;
        }
        new Thread(()->run(protocol,port,token),"p2-fixture").start();
    }
    private void busy(){nativeButton.setEnabled(false);webButton.setEnabled(false);status.setText("sending:"+count);}
    private void finishWeb(String token,boolean ok){
        JSONObject report=new JSONObject();try{report.put("token",token);report.put("protocol","webview-http");report.put("status",ok?"succeeded":"failed");report.put("echo",ok?token:"");report.put("finished_ms",System.currentTimeMillis());
            try(FileOutputStream file=openFileOutput("receipt.json",MODE_PRIVATE)){file.write(report.toString().getBytes(StandardCharsets.UTF_8));}
        }catch(Exception e){ok=false;}
        status.setText(ok?"sent:"+count:"failed:"+count);nativeButton.setEnabled(true);webButton.setEnabled(true);
    }
    private Socket connect(boolean tls,int port) throws Exception {
        Socket plain=new Socket();plain.connect(new InetSocketAddress("127.0.0.1",port),3000);plain.setSoTimeout(3000);
        if(!tls)return plain; // Raw, hardcoded loopback fixture; never arbitrary cleartext destinations.
        try {
            KeyStore store=KeyStore.getInstance(KeyStore.getDefaultType());store.load(null);
            try(InputStream ca=getAssets().open("qa-ca.pem")) {
                store.setCertificateEntry("qa-only",CertificateFactory.getInstance("X.509").generateCertificate(ca));
            }
            TrustManagerFactory tm=TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());tm.init(store);
            SSLContext context=SSLContext.getInstance("TLS");context.init(null,tm.getTrustManagers(),null);
            SSLSocket socket=(SSLSocket)context.getSocketFactory().createSocket(plain,"localhost",port,true);
            SSLParameters params=socket.getSSLParameters();params.setEndpointIdentificationAlgorithm("HTTPS");socket.setSSLParameters(params);
            socket.startHandshake();return socket;
        } catch(Exception e) { plain.close();throw e; }
    }
    private static byte[] exact(InputStream in,int n) throws IOException {
        byte[] data=new byte[n];int at=0;while(at<n){int count=in.read(data,at,n-at);if(count<0)throw new EOFException();at+=count;}return data;
    }
    private static String headers(InputStream in) throws IOException {
        ByteArrayOutputStream bytes=new ByteArrayOutputStream();int match=0;byte[] end={13,10,13,10};
        while(bytes.size()<16384) { int b=in.read();if(b<0)throw new EOFException();bytes.write(b);match=(b==end[match])?match+1:(b==13?1:0);if(match==4)return bytes.toString("US-ASCII"); }
        throw new IOException("header_limit");
    }
    private static void frame(OutputStream out,int opcode,byte[] data) throws Exception {
        if(data.length>125)throw new IOException("fixture_frame_limit");
        byte[] mask=new byte[4];new SecureRandom().nextBytes(mask);out.write(0x80|opcode);out.write(0x80|data.length);out.write(mask);
        for(int i=0;i<data.length;i++)out.write(data[i]^mask[i%4]);out.flush();
    }
    private static byte[] receive(InputStream in,int opcode) throws Exception {
        byte[] head=exact(in,2);int len=head[1]&255;
        if((head[0]&255)!=(0x80|opcode) || len>125)throw new IOException("unexpected_fixture_frame");
        return exact(in,len);
    }
    private void run(String protocol,int port,String token) {
        JSONObject report=new JSONObject();
        try {
            report.put("protocol",protocol);report.put("token",token);report.put("started_ms",System.currentTimeMillis());
            boolean ws=protocol.startsWith("ws"),tls=protocol.equals("https")||protocol.equals("wss");
            try(Socket socket=connect(tls,port)) {
                InputStream in=socket.getInputStream();OutputStream out=socket.getOutputStream();
                String request="GET /synthetic/"+token+" HTTP/1.1\r\nHost: localhost\r\n";
                if(ws)request+="Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: c3ludGhldGljLXBvYy1rZQ==\r\n\r\n";
                else request+="Content-Length: 0\r\nConnection: close\r\n\r\n";
                out.write(request.getBytes(StandardCharsets.US_ASCII));out.flush();String head=headers(in);
                if(ws) {
                    if(!head.startsWith("HTTP/1.1 101 ")||!head.toLowerCase().contains("sec-websocket-accept: 7sbntugfmflpglbjp/c9zzsznl4="))throw new IOException("handshake_mismatch");
                    byte[] data=token.getBytes(StandardCharsets.UTF_8);frame(out,1,data);
                    if(!java.util.Arrays.equals(data,receive(in,1)))throw new IOException("echo_mismatch");
                    frame(out,8,new byte[]{3,(byte)232});receive(in,8);report.put("echo",token);
                } else {
                    if(!head.startsWith("HTTP/1.1 200 "))throw new IOException("status_mismatch");
                    int length=-1;for(String line:head.split("\r\n"))if(line.toLowerCase().startsWith("content-length:"))length=Integer.parseInt(line.substring(15).trim());
                    if(length<0||length>4096)throw new IOException("body_limit");
                    String body=new String(exact(in,length),StandardCharsets.UTF_8);
                    if(!body.equals(token))throw new IOException("body_mismatch");report.put("echo",body);
                }
                report.put("status","succeeded");
            }
        } catch(Exception e) { try {report.put("status","failed");report.put("error",e.getClass().getSimpleName());}catch(Exception ignored){} }
        try {
            report.put("finished_ms",System.currentTimeMillis());
            try(FileOutputStream file=openFileOutput("receipt.json",MODE_PRIVATE)){file.write(report.toString().getBytes(StandardCharsets.UTF_8));}
        } catch(Exception e) {runOnUiThread(()->status.setText("Receipt write failed"));return;}
        runOnUiThread(()->{if(interactive){status.setText(report.optString("status").equals("succeeded")?"sent:"+count:"failed:"+count);nativeButton.setEnabled(true);webButton.setEnabled(true);}else status.setText("P2 DISPOSABLE NETWORK QA\n"+report.toString());});
    }
}
