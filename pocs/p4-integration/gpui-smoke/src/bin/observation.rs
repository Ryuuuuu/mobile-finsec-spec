use gpui_kit::*;
use gpui_kit::component::{button::{Button,ButtonVariants},label::Label,Disableable};
use serde_json::{Value,json};
use std::{sync::{Arc,Mutex},time::Duration};
#[path="../session.rs"]mod session;

struct Observation{tab:u8,busy:bool,active:bool,blocked:bool,status:String,preview:Value,approved:String,progress:Value,result:Value,transport:Arc<Mutex<Option<session::Session>>>}
impl Observation{
 fn new()->Self{Self{tab:1,busy:false,active:false,blocked:false,status:"Load a fixed synthetic plan; no device or model".into(),preview:Value::Null,approved:String::new(),progress:Value::Null,result:Value::Null,transport:Arc::new(Mutex::new(None))}}
 fn send(&mut self,op:&'static str,args:Value,cx:&mut Context<Self>){
  if self.busy||self.blocked{return;}self.busy=true;let transport=self.transport.clone();cx.notify();
  cx.spawn(async move|entity,cx|{let reply=cx.background_executor().spawn(async move{let mut guard=transport.lock().map_err(|_|"Owner unavailable".to_string())?;if guard.is_none(){*guard=Some(session::Session::start_observation()?);}guard.as_mut().unwrap().exchange(op,args)}).await;
   let _=entity.update(cx,|t,cx|{t.busy=false;match reply{Err(e)=>{t.status=format!("BLOCKED: {e}");t.blocked=true;t.active=false;},Ok(v)=>{
    t.status=format!("{}: {}",op,v["status"]);
    match op{"preview"|"new_version"=>{t.preview=v;},"approve"=>{if v["status"]=="approved"{t.approved=v["plan_hash"].as_str().unwrap_or("").into();}},"start"=>{if v["status"]=="accepted"{t.active=true;t.result=Value::Null;t.progress=Value::Null;t.poll_later(cx);}},"status"=>{t.progress=v.clone();if v["final_available"]==true{t.active=false;t.status="Replay finished; review finalized separately. Open Results.".into();}else if v["status"]=="EXECUTION_OR_STORAGE_ERROR"{t.active=false;t.blocked=true;}else if t.active{t.poll_later(cx);}},"result"=>{if v["status"]=="ok"{t.result=v["result"].clone();}},_=>{}}
   }}cx.notify();});}).detach();
 }
 fn poll_later(&mut self,cx:&mut Context<Self>){cx.spawn(async move|entity,cx|{cx.background_executor().timer(Duration::from_millis(150)).await;let _=entity.update(cx,|t,cx|{if t.active{if t.busy{t.poll_later(cx);}else{t.send("status",json!({}),cx);}}});}).detach();}
}
fn row_text(row:&Value)->String{format!("{} / step {} / {} | evidence {} | review {} | reason {}",row["checkpoint"]["recording_id"],row["checkpoint"]["step_id"],row["checkpoint"]["phase"],if row["evidence_ref"].is_string(){1}else{0},row["review"],row["reason"])}
impl Render for Observation{fn render(&mut self,_:&mut Window,cx:&mut Context<Self>)->impl IntoElement{
 let mut body=div().flex().flex_col().gap_3();
 if self.tab==0{body=body.child(Label::new("Record / Fixed synthetic routes A -> B only. No recording or inspection selection here."));}
 else if self.tab==1{
  let hash=self.preview["plan_hash"].as_str().unwrap_or("").to_string();
  let approval=if self.approved.is_empty(){"not approved"}else if self.approved==hash{"approved current version"}else{"STALE approval - version mismatch"};
  body=body.child(Label::new("Check / Read-only observation plan preview - fixed fake reviewer"))
   .child(Button::new("preview").label("Load fixed plan").disabled(self.busy||self.active||self.blocked).on_click(cx.listener(|t,_,_,cx|t.send("preview",json!({}),cx))))
   .child(Label::new(format!("Version {} | {} | {}",self.preview["revision"],self.preview["scenario"],approval)))
   .child(Label::new(format!("Plan hash: {}",hash)))
   .child(Label::new(format!("Capture deadline {}s / review deadline {}s. Fixed QA state only; no raw images, packets or inputs.",self.preview["capture_timeout"],self.preview["review_timeout"])));
  for (i,c) in self.preview["checkpoints"].as_array().into_iter().flatten().enumerate(){body=body.child(Label::new(format!("{} / {} {} / step {} / {} / expected {} / state-only evidence",c["check_id"],c["recording_id"],c["route_version"],c["step_id"],c["phase"],c["expected"])).id(("cp",i)));}
  body=body.child(Button::new("approve").label("Approve displayed plan hash").disabled(hash.is_empty()||self.active||self.busy||self.blocked).on_click(cx.listener(|t,_,_,cx|t.send("approve",json!({"plan_hash":t.preview["plan_hash"]}),cx))))
   .child(Button::new("version").label("Load newer fixed version / B missing evidence").disabled(hash.is_empty()||self.active||self.busy||self.blocked).on_click(cx.listener(|t,_,_,cx|t.send("new_version",json!({}),cx))))
   .child(Button::new("run").primary().label("Run using last approved hash (stale is rejected)").disabled(self.approved.is_empty()||self.active||self.busy||self.blocked).on_click(cx.listener(|t,_,_,cx|t.send("start",json!({"plan_hash":t.approved}),cx))))
   .child(Label::new(format!("Live replay: {} | review/finalization: {}",self.progress["replay"],self.progress["status"])));
  for (i,r) in self.progress["rows"].as_array().into_iter().flatten().enumerate(){body=body.child(Label::new(row_text(r)).id(("live",i)));}
 }else{
  body=body.child(Label::new("Results / Finalized observation results only"))
   .child(Button::new("result").label("Load final result").disabled(self.busy||self.active||self.blocked).on_click(cx.listener(|t,_,_,cx|t.send("result",json!({}),cx))))
   .child(Label::new(format!("Replay: {} | Finalization: {} | Coverage: {} / {} routes",self.result["replay_status"],self.result["finalization"],self.result["checks"]["mock-check"]["routes_with_evidence"],self.result["checks"]["mock-check"]["routes_expected"])));
  for (i,r) in self.result["rows"].as_array().into_iter().flatten().enumerate(){body=body.child(Label::new(row_text(r)).id(("final",i)));}
  body=body.child(Label::new("Observation-only / inconclusive. No enforcement or security verdict established."));
 }
 div().flex().flex_col().size_full().p_6().gap_4().child(Label::new("Finsec Observation POC - SYNTHETIC ONLY / NO DEVICE / NO MODEL"))
 .child(div().flex().gap_3().children([("Record",0),("Check",1),("Results",2)].into_iter().map(|(s,i)|Button::new(("tab",i as usize)).label(s).on_click(cx.listener(move|t,_,_,cx|{t.tab=i;cx.notify();})))))
 .child(Label::new(self.status.clone())).child(body)
}}
fn main(){application().with_assets(assets::Assets).run(|cx|{init(cx);open_window(WindowOptions::default(),cx,|_,cx|cx.new(|_|Observation::new())).expect("observation window");});}

#[cfg(test)]mod tests{use super::{row_text,session};use serde_json::json;use std::time::Duration;
 #[test]fn coverage_row_keeps_gap_reason(){let row=json!({"checkpoint":{"recording_id":"route-B","step_id":"tap","phase":"after_postcondition"},"evidence_ref":null,"review":"NOT_REVIEWED","reason":"EVIDENCE_INSUFFICIENT"});let text=row_text(&row);assert!(text.contains("route-B")&&text.contains("evidence 0")&&text.contains("EVIDENCE_INSUFFICIENT"));}
 #[test]#[ignore="requires existing Python and disposable observation root"]fn actual_observation_pipe_contract(){
  let mut s=session::Session::start_observation().unwrap();
  let first=s.exchange("preview",json!({})).unwrap();let old=first["plan_hash"].clone();
  assert_eq!(s.exchange("start",json!({"plan_hash":old})).unwrap()["status"],"PLAN_NOT_APPROVED");
  assert_eq!(s.exchange("approve",json!({"plan_hash":old})).unwrap()["status"],"approved");
  let changed=s.exchange("new_version",json!({})).unwrap();let hash=changed["plan_hash"].clone();
  assert_eq!(s.exchange("start",json!({"plan_hash":old})).unwrap()["status"],"PLAN_VERSION_MISMATCH");
  s.exchange("approve",json!({"plan_hash":hash})).unwrap();
  assert_eq!(s.exchange("start",json!({"plan_hash":hash})).unwrap()["status"],"accepted");
  let until=std::time::Instant::now()+Duration::from_secs(15);let mut pending=false;
  loop{let p=s.exchange("status",json!({})).unwrap();if p["status"]=="review_pending"{assert_eq!(p["replay"],"completed");pending=true;}if p["final_available"]==true{break;}assert!(std::time::Instant::now()<until);std::thread::sleep(Duration::from_millis(20));}
  assert!(pending);let r=s.exchange("result",json!({})).unwrap();assert_eq!(r["result"]["checks"]["mock-check"]["routes_with_evidence"],1);assert_eq!(r["result"]["checks"]["mock-check"]["routes_expected"],2);
  assert_eq!(r["result"]["rows"][0]["review"],"REVIEW_TIMEOUT");assert_eq!(r["result"]["rows"][1]["reason"],"EVIDENCE_INSUFFICIENT");
 }
}
