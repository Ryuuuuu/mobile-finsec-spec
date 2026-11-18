use gpui_kit::*;
use gpui_kit::component::{button::{Button,ButtonVariants},checkbox::Checkbox,label::Label,Disableable};
use serde_json::{Value,json};
use std::{sync::{Arc,Mutex},time::{Duration,SystemTime,UNIX_EPOCH}};
#[path="../session.rs"]mod session;
#[path="../queue_plan.rs"]mod queue_plan;
use queue_plan::QueuePlan;
struct Workspace{live:bool,tab:u8,session:Arc<Mutex<Option<session::Session>>>,busy:bool,active:bool,blocked:bool,item:bool,status:String,records:Vec<Value>,selected:Vec<String>,history:Vec<Value>,events:Vec<String>,detail:Vec<String>,execution:String,cursor:u64,request:Value,queue:QueuePlan}
impl Workspace{
 fn new()->Self{Self{live:std::env::var_os("FINSEC_QA_CONFIG").is_some(),tab:0,session:Arc::new(Mutex::new(None)),busy:false,active:false,blocked:false,item:false,status:"Python not connected".into(),records:vec![],selected:vec![],history:vec![],events:vec![],detail:vec![],execution:String::new(),cursor:0,request:Value::Null,queue:QueuePlan::default()}}
 fn send(&mut self,op:&'static str,args:Value,cx:&mut Context<Self>){
  if self.busy{return;}self.busy=true;let transport=self.session.clone();cx.notify();
  cx.spawn(async move|entity,cx|{let reply=cx.background_executor().spawn(async move{let mut guard=transport.lock().map_err(|_|"Transport owner unavailable".to_string())?;if guard.is_none(){*guard=Some(session::Session::start()?);}guard.as_mut().unwrap().exchange(op,args)}).await;
   let _=entity.update(cx,|this,cx|{this.busy=false;match reply{Ok(v)=>this.received(op,v,cx),Err(e)=>{this.status=format!("BLOCKED / outcome unknown: {e}");this.blocked=true;this.active=false;this.queue.terminal(false);}}cx.notify();});}).detach();
 }
 fn start_queue(&mut self,cx:&mut Context<Self>){self.active=true;self.events.clear();if self.live{let id=format!("native-qa-{}",SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos());self.request=json!({"command_id":id,"recording_refs":self.selected});self.status="Submitting real QA queue; preparation and cleanup are asynchronous".into();self.send("submit",json!({"request":self.request}),cx);}else{self.queue=QueuePlan::new(self.selected.clone());self.next(cx);}}
 fn next(&mut self,cx:&mut Context<Self>){if let Some(route)=self.queue.next(){let id=format!("native-{}-{}",SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos(),self.queue.index);self.request=session::request(route.as_deref(),&id);self.status=format!("Preflight queue {}/{}: {}",self.queue.index,self.queue.routes.len(),route.as_deref().unwrap_or("app launch default"));self.send("inspect",json!({"request":self.request}),cx);}else{self.active=false;self.status=if self.queue.stopped{"Queue stopped; remaining routes not run"}else{"Queue completed; open Result logs for finalized results"}.into();}}
 fn schedule_poll(&mut self,cx:&mut Context<Self>){cx.spawn(async move|entity,cx|{cx.background_executor().timer(Duration::from_millis(150)).await;let _=entity.update(cx,|this,cx|{if this.active{if this.busy{this.schedule_poll(cx);}else{this.poll(cx);}}});}).detach();}
 fn poll(&mut self,cx:&mut Context<Self>){self.send("progress",json!({"execution_id":self.execution,"cursor":self.cursor}),cx);}
 fn received(&mut self,op:&str,v:Value,cx:&mut Context<Self>){match op{
  "recordings"=>{self.records=v["recordings"].as_array().cloned().unwrap_or_default();self.status=format!("Recording catalog: {} entries / {}",self.records.len(),v["status"]);},
  "inspect"=>{if v["data"]["enabled"]==true{self.send("submit",json!({"request":self.request}),cx)}else{self.queue.terminal(false);self.active=false;self.status=format!("Not run: {}",v["data"]["reasons"]);}},
  "submit"=>{if matches!(v["data"]["status"].as_str(),Some("accepted"|"duplicate")){self.execution=v["data"]["execution_id"].as_str().unwrap_or("").into();self.cursor=0;self.status=if self.live{"Actual QA queue running / Python owns device and cleanup".into()}else{format!("Running queue {}/{}",self.queue.index,self.queue.routes.len())};self.poll(cx);}else{self.queue.terminal(false);self.active=false;self.status=format!("Admission stopped: {}",v["data"]["status"]);}},
  "progress"=>{if v["resync_required"]==true||!v["delivery_error"].is_null(){self.queue.terminal(false);self.blocked=true;self.active=false;self.status="Progress delivery incomplete; reconciliation required".into();return;}
   for e in v["events"].as_array().into_iter().flatten(){self.events.push(if self.live{format!("QA event {}: {}",e["seq"],e["type"])}else{format!("Route {} / event {}: {}",self.queue.index,e["seq"],e["type"])});}if self.events.len()>80{self.events.drain(..self.events.len()-80);}self.cursor=v["next_cursor"].as_u64().unwrap_or(self.cursor);
   if v["has_more"]==true{self.schedule_poll(cx);return;}
   match v["execution"]["status"].as_str(){Some("finished")=>{if self.live{self.active=false;self.blocked=v["execution"]["cleanup_verified"]!=true;self.status=format!("Actual QA queue {} / cleanup {} / open Results",v["execution"]["execution_status"],if self.blocked{"UNCONFIRMED - blocked"}else{"verified"});return;}self.events.push(format!("Route {} terminal: {}",self.queue.index,v["execution"]["execution_status"]));self.queue.terminal(v["execution"]["execution_status"]=="completed");self.next(cx);},Some("in_progress")=>{self.schedule_poll(cx);},_=>{self.queue.terminal(false);self.active=false;self.status=format!("Execution unresolved: {}",v["execution"]["status"]);}}},
  "cancel"=>{self.status=format!("Cancel response: {}",v["data"]["status"]);self.poll(cx);},
  "history"=>{self.history=v["runs"].as_array().cloned().unwrap_or_default();self.status=format!("Finalized results: {}",self.history.len());},
  "result"=>{self.detail.clear();self.detail.push(format!("Storage: {}",v["status"]));if v["status"]=="ok"{let r=&v["result"];self.detail.push(format!("Execution: {} / completion: {}",r["execution_status"],r["completion"]));for i in r["items"].as_array().into_iter().flatten(){self.detail.push(format!("{}: {} / {}",i["item_id"],i["execution_status"],i["reason"]));if self.live{self.detail.push(format!("Replay {} / network {} / packets {}",i["replay_run_id"],i["network_recording_id"],i["packet_count"]));}let c=&i["recording_context"];self.detail.push(format!("Record {} / route {} / packets {}",c["recording_id"],c["route_status"],c["packet_status"]));}self.detail.push(if self.live{"Actual device QA replay only; no inspection or model"}else{"No security verdict: opaque mock executor only"}.into());}},_=>{}
 }}
}
impl Render for Workspace{fn render(&mut self,_:&mut Window,cx:&mut Context<Self>)->impl IntoElement{
 let mut body=div().flex().flex_col().gap_3();
 if self.tab==0{
  body=body.child(Label::new(if self.live{"기록 / Private QA routes - REAL DEVICE mode"}else{"기록 / Multiple saved routes - MOCK artifacts"}))
   .child(Label::new(if self.live{"Select in order. Disposable QA app only. Each route has independent WSS capture and results."}else{"Select in playback order. One device, one route at a time. No selection = app-launch intent."}))
   .child(Button::new("refresh-records").label("Refresh recordings").disabled(self.busy||self.active).on_click(cx.listener(|t,_,_,cx|t.send("recordings",json!({}),cx))));
  for (i,row) in self.records.iter().take(20).enumerate(){let reference=row["ref"].as_str().unwrap_or("").to_string();let enabled=row["selectable"]==true;let pos=self.selected.iter().position(|r|r==&reference);let label=format!("{} {} | {} | route={} packets={}",pos.map(|p|(p+1).to_string()).unwrap_or("-".into()),row["display_name"].as_str().unwrap_or(&reference),row["recorded_at"].as_str().unwrap_or("time unavailable"),row["recording"]["route_status"],row["recording"]["packet_status"]);
   body=body.child(Checkbox::new(("route",i)).label(label).checked(pos.is_some()).disabled(!enabled||self.active||self.busy).on_click(cx.listener(move|t,checked,_,cx|{if *checked{if !t.selected.contains(&reference){t.selected.push(reference.clone());}}else{t.selected.retain(|r|r!=&reference);}cx.notify();})));
  }
  body=body.child(Label::new(format!("Queue order: {}",if self.selected.is_empty(){"default app-launch".into()}else{self.selected.join(" -> ")})))
   .child(Button::new("clear").label("Clear queue / reorder by selecting again").disabled(self.active||self.busy).on_click(cx.listener(|t,_,_,cx|{t.selected.clear();cx.notify();})));
 }else if self.tab==1{
  body=body.child(Label::new(if self.live{"점검 / Actual QA route replay - no inspection skills"}else{"점검 / Synthetic device - sequential mock execution"}))
   .child(Checkbox::new("mock-item").label(if self.live{"Reviewed disposable QA routes; run with existing approved settings"}else{"mock-item (opaque common + AOS skills)"}).checked(self.item).disabled(self.active||self.busy).on_click(cx.listener(|t,v,_,cx|{t.item=*v;cx.notify();})))
   .child(Label::new(format!("Selected route queue: {}",if self.selected.is_empty(){"app-launch default".into()}else{self.selected.join(" -> ")})))
   .child(Button::new("start").primary().label("Start selected queue / repeat").disabled(!self.item||self.active||self.busy||self.blocked||(self.live&&self.selected.is_empty())).on_click(cx.listener(|t,_,_,cx|{t.start_queue(cx);})))
   .child(Button::new("cancel").label("Cancel queue").disabled(!self.active||self.busy).on_click(cx.listener(|t,_,_,cx|{t.queue.cancel();t.send("cancel",json!({"execution_id":t.execution}),cx);})))
   .child(Label::new("Live progress (not final result logs):"));
  for (i,event) in self.events.iter().enumerate().rev().take(14).rev(){body=body.child(Label::new(event.clone()).id(("live-event",i)));}
 }else{
  body=body.child(Label::new("결과 로그 / Finalized runs only - no live events"))
   .child(Button::new("history").label("Refresh result history").disabled(self.busy).on_click(cx.listener(|t,_,_,cx|t.send("history",json!({}),cx))));
  for (i,row) in self.history.iter().take(12).enumerate(){let rid=row["run_id"].as_str().unwrap_or("").to_string();let label=format!("{} | {} | {}",row["started_at"].as_str().unwrap_or("unknown time"),row["execution_status"].as_str().unwrap_or("unknown"),rid);
   body=body.child(Button::new(("run",i)).label(label).disabled(self.busy).on_click(cx.listener(move|t,_,_,cx|t.send("result",json!({"run_id":rid}),cx))));}
  for (i,line) in self.detail.iter().enumerate(){body=body.child(Label::new(line.clone()).id(("result-line",i)));}
 }
 div().flex().flex_col().size_full().p_6().gap_4().child(Label::new(if self.live{"Finsec Workspace POC - REAL QA DEVICE / NO MODEL / NO INSPECTION"}else{"Finsec Workspace POC - MOCK ONLY / NO DEVICE / NO MODEL"}))
 .child(div().flex().gap_3().children([("기록 / Record",0),("점검 / Check",1),("결과 로그 / Results",2)].into_iter().map(|(name,id)|Button::new(("tab",id as usize)).label(name).on_click(cx.listener(move|t,_,_,cx|{t.tab=id;cx.notify();})))))
 .child(Label::new(self.status.clone())).child(body)
}}
fn main(){application().with_assets(assets::Assets).run(|cx|{init(cx);open_window(WindowOptions::default(),cx,|_,cx|cx.new(|_|Workspace::new())).expect("workspace window");});}
