use gpui_kit::*;
use gpui_kit::component::{button::{Button,ButtonVariants},label::Label,Disableable};
use serde_json::{Value,json};
use std::{sync::{Arc,Mutex},time::Duration};
#[path="../session.rs"]mod session;

struct Observation{tab:u8,busy:bool,active:bool,blocked:bool,status:String,preview:Value,approved:String,progress:Value,result:Value,history:Value,transport:Arc<Mutex<Option<session::Session>>>}
impl Observation{
 fn new()->Self{Self{tab:1,busy:false,active:false,blocked:false,status:"Load a fixed synthetic plan; no device or model".into(),preview:Value::Null,approved:String::new(),progress:Value::Null,result:Value::Null,history:Value::Null,transport:Arc::new(Mutex::new(None))}}
 fn send(&mut self,op:&'static str,args:Value,cx:&mut Context<Self>){
  if self.busy||self.blocked{return;}self.busy=true;let transport=self.transport.clone();cx.notify();
  cx.spawn(async move|entity,cx|{let reply=cx.background_executor().spawn(async move{let mut guard=transport.lock().map_err(|_|"Owner unavailable".to_string())?;if guard.is_none(){*guard=Some(session::Session::start_observation()?);}guard.as_mut().unwrap().exchange(op,args)}).await;
   let _=entity.update(cx,|t,cx|{t.busy=false;match reply{Err(e)=>{t.status=format!("BLOCKED: {e}");t.blocked=true;t.active=false;},Ok(v)=>{
    t.status=format!("{}: {}",op,v["status"]);
    match op{"preview"|"new_version"=>{t.preview=v;},"approve"=>{if v["status"]=="approved"{t.approved=v["plan_hash"].as_str().unwrap_or("").into();}},"start"=>{if v["status"]=="accepted"{t.active=true;t.result=Value::Null;t.progress=Value::Null;t.poll_later(cx);}},"status"=>{t.progress=v.clone();if v["final_available"]==true{t.active=false;t.status="Replay finished; review finalized separately. Open Results.".into();}else if v["status"]=="EXECUTION_OR_STORAGE_ERROR"{t.active=false;t.blocked=true;}else if t.active{t.poll_later(cx);}},"history"=>{t.history=v;},"result"|"load_completed"=>{t.result=report_value(&v);},_=>{}}
   }}cx.notify();});}).detach();
 }
 fn poll_later(&mut self,cx:&mut Context<Self>){cx.spawn(async move|entity,cx|{cx.background_executor().timer(Duration::from_millis(150)).await;let _=entity.update(cx,|t,cx|{if t.active{if t.busy{t.poll_later(cx);}else{t.send("status",json!({}),cx);}}});}).detach();}
}
fn report_value(reply:&Value)->Value{if reply["status"]!="ok"{return Value::Null;}let mut result=reply["result"].clone();result["matching_report"]=reply["matching_report"].clone();result["saved_at"]=reply["saved_at"].clone();result["historical_detail"]=reply["historical_detail"].clone();result}
fn history_label(row:&Value)->String{format!("{} UTC | run {}",row["saved_at"].as_str().unwrap_or("DATE_UNAVAILABLE"),row["run_id"].as_str().unwrap_or("unknown"))}
fn checkpoint_text(c:&Value)->String{let execution=c["occurrence"].as_u64().and_then(|n|n.checked_add(1)).map(|n|n.to_string()).unwrap_or("unknown".into());let mut text=format!("{} {} / execution {}",c["recording_id"],c["route_version"],execution);if let Some(step)=c["step_id"].as_str(){text.push_str(&format!(" / step {step}"));}if let Some(phase)=c["phase"].as_str(){text.push_str(&format!(" / {phase}"));}text}
fn row_text(row:&Value)->String{format!("{} / {} | evidence {} | review {} | reason {}",row["checkpoint"]["check_id"],checkpoint_text(&row["checkpoint"]),if row["evidence_ref"].is_string(){1}else{0},row["review"],row["reason"])}
fn check_summaries(result:&Value)->Vec<String>{result["checks"].as_object().into_iter().flat_map(|checks|checks.iter().map(|(id,c)|format!("{id}: coverage {} / {} | unknown {} | excluded {} | {} / {}",c["routes_with_evidence"],c["routes_expected"],c.get("routes_unknown").unwrap_or(&Value::Null),c.get("routes_not_applicable").unwrap_or(&Value::Null),c["verdict"],c["reason"]))).collect()}
fn matching_text(r:&Value)->String{format!("{} / {} | timing match {}",r["check_id"],checkpoint_text(r),r["status"])}
impl Render for Observation{fn render(&mut self,_:&mut Window,cx:&mut Context<Self>)->impl IntoElement{
 let mut body=div().flex().flex_col().gap_3();
 if self.tab==0{body=body.child(Label::new("Record / Same synthetic route twice: execution 1 -> 2. No recording or inspection selection here."));}
 else if self.tab==1{
  let hash=self.preview["plan_hash"].as_str().unwrap_or("").to_string();
  let approval=if self.approved.is_empty(){"not approved"}else if self.approved==hash{"approved current version"}else{"STALE approval - version mismatch"};
  body=body.child(Label::new("Check / Read-only observation plan preview - fixed fake reviewer"))
   .child(Button::new("preview").label("Load fixed plan").disabled(self.busy||self.active||self.blocked).on_click(cx.listener(|t,_,_,cx|t.send("preview",json!({}),cx))))
   .child(Label::new(format!("Version {} | {} | {}",self.preview["revision"],self.preview["scenario"],approval)))
   .child(Label::new(format!("Plan hash: {}",hash)))
   .child(Label::new(format!("Capture deadline {}s / review deadline {}s. Fixed QA state only; no raw images, packets or inputs.",self.preview["capture_timeout"],self.preview["review_timeout"])));
  for (i,c) in self.preview["checkpoints"].as_array().into_iter().flatten().enumerate(){body=body.child(Label::new(format!("{} / {} / expected {} / state-only evidence",c["check_id"],checkpoint_text(c),c["expected"])).id(("cp",i)));}
  for (i,r) in self.preview["matching_report"]["rules"].as_array().into_iter().flatten().enumerate(){body=body.child(Label::new(format!("Timing {} / {}: {}={} / {} / evidence {}",r["schema_version"],r["check_id"],r["condition_kind"],r["condition_value"],r["phase"],r["required_evidence"])).id(("rule",i)));}
  for (i,r) in self.preview["matching_report"]["rows"].as_array().into_iter().flatten().enumerate(){body=body.child(Label::new(format!("{} / {} | match {} | candidates {}",r["check_id"],checkpoint_text(r),r["status"],r["candidate_count"])).id(("match",i)));}
  body=body.child(Button::new("approve").label("Approve displayed plan hash").disabled(hash.is_empty()||self.active||self.busy||self.blocked).on_click(cx.listener(|t,_,_,cx|t.send("approve",json!({"plan_hash":t.preview["plan_hash"]}),cx))))
   .child(Button::new("version").label("Load newer fixed plan version").disabled(hash.is_empty()||self.active||self.busy||self.blocked).on_click(cx.listener(|t,_,_,cx|t.send("new_version",json!({}),cx))))
   .child(Button::new("run").primary().label("Run using last approved hash (stale is rejected)").disabled(self.approved.is_empty()||self.active||self.busy||self.blocked).on_click(cx.listener(|t,_,_,cx|t.send("start",json!({"plan_hash":t.approved}),cx))))
   .child(Label::new(format!("Live replay: {} | review/finalization: {}",self.progress["replay"],self.progress["status"])));
  for (i,r) in self.progress["rows"].as_array().into_iter().flatten().enumerate(){body=body.child(Label::new(row_text(r)).id(("live",i)));}
 }else{
  body=body.child(Label::new("Results / Finalized observation results only"))
   .child(Button::new("result").label("Load final result").disabled(self.busy||self.active||self.blocked).on_click(cx.listener(|t,_,_,cx|t.send("result",json!({}),cx))))
   .child(Button::new("history").label("Refresh completed history (read-only)").disabled(self.busy||self.active||self.blocked).on_click(cx.listener(|t,_,_,cx|t.send("history",json!({}),cx))))
   .child(Label::new(format!("History: {}",self.history["status"])));
  for (i,r) in self.history["history"].as_array().into_iter().flatten().enumerate(){let args=json!({"run_id":r["run_id"],"plan_hash":r["plan_hash"]});body=body.child(Button::new(("history-entry",i)).label(history_label(r)).disabled(self.busy||self.active||self.blocked||r["available"]!=true).on_click(cx.listener(move|t,_,_,cx|t.send("load_completed",args.clone(),cx)))).child(Label::new(format!("{}",r["reason"])).id(("history-status",i)));}
  body=body.child(Label::new(format!("Selected run: {} | saved: {} | historical detail: {}",self.result["run_id"],self.result["saved_at"],self.result["historical_detail"])))
   .child(Label::new(format!("Replay: {} | Finalization: {}",self.result["replay_status"],self.result["finalization"])));
  for (i,text) in check_summaries(&self.result).into_iter().enumerate(){body=body.child(Label::new(text).id(("summary",i)));}
  for (i,r) in self.result["rows"].as_array().into_iter().flatten().enumerate(){body=body.child(Label::new(row_text(r)).id(("final",i)));}
  for (i,r) in self.result["matching_report"]["rows"].as_array().into_iter().flatten().enumerate(){body=body.child(Label::new(matching_text(r)).id(("finalmatch",i)));}
  body=body.child(Label::new("Observation-only / inconclusive. No enforcement or security verdict established."));
 }
 div().flex().flex_col().size_full().p_6().gap_4().child(Label::new("Finsec Observation POC - SYNTHETIC ONLY / NO DEVICE / NO MODEL"))
 .child(div().flex().gap_3().children([("Record",0),("Check",1),("Results",2)].into_iter().map(|(s,i)|Button::new(("tab",i as usize)).label(s).on_click(cx.listener(move|t,_,_,cx|{t.tab=i;cx.notify();})))))
 .child(Label::new(self.status.clone())).child(div().id("observation-scroll").flex_1().min_h_0().overflow_y_scroll().child(body))
}}
fn main(){application().with_assets(assets::Assets).run(|cx|{init(cx);open_window(WindowOptions::default(),cx,|_,cx|cx.new(|_|Observation::new())).expect("observation window");});}

#[cfg(test)]mod tests{use super::{checkpoint_text,row_text,matching_text,check_summaries,report_value,history_label,session};use serde_json::json;use std::time::Duration;
 #[test]fn history_identity_and_failed_selection(){let a=json!({"saved_at":"2026-11-19T12:00:00.000Z","run_id":"run-a"});let b=json!({"saved_at":"2026-11-19T12:00:00.000Z","run_id":"run-b"});assert_ne!(history_label(&a),history_label(&b));assert!(history_label(&json!({"run_id":"old"})).contains("DATE_UNAVAILABLE"));assert!(report_value(&json!({"status":"COMPLETED_REPORT_UNAVAILABLE_OR_INVALID"})).is_null());let r=report_value(&json!({"status":"ok","result":{"run_id":"old"},"matching_report":null,"historical_detail":"HISTORICAL_TIMING_UNAVAILABLE"}));assert_eq!(r["historical_detail"],"HISTORICAL_TIMING_UNAVAILABLE");}
 #[test]fn final_matching_reasons_remain_distinct(){let mut r=json!({"check_id":"before-check","recording_id":"route-A","route_version":"v1","occurrence":1,"status":"UNMATCHED"});let a=matching_text(&r);r["status"]=json!("AMBIGUOUS");let b=matching_text(&r);assert!(a.contains("UNMATCHED")&&b.contains("AMBIGUOUS"));assert_ne!(a,b);assert!(a.contains("execution 2")&&!a.contains("step null"));}
 #[test]fn per_check_summaries_and_report_only_rows(){let result=json!({"checks":{"before-check":{"routes_with_evidence":1,"routes_expected":2},"after-check":{"routes_with_evidence":0,"routes_expected":2}}});let summaries=check_summaries(&result);assert!(summaries.iter().any(|s|s.contains("before-check: coverage 1 / 2")));assert!(summaries.iter().any(|s|s.contains("after-check: coverage 0 / 2")));let text=row_text(&json!({"checkpoint":{"check_id":"after-check","recording_id":"route-A","route_version":"v1","occurrence":0,"step_id":null,"phase":null},"reason":"PLAN_CHECKPOINT_MISSING"}));assert!(text.contains("after-check")&&text.contains("execution 1")&&text.contains("PLAN_CHECKPOINT_MISSING"));assert!(!text.contains("step null")&&!text.contains(" / null"));assert!(check_summaries(&json!({"checks":{"mock-check":{"routes_with_evidence":1,"routes_expected":2}}}))[0].contains("mock-check: coverage 1 / 2"));}
 #[test]fn repeated_selection_identity_is_visible_on_all_row_surfaces(){let c=json!({"recording_id":"route-A","route_version":"v2","occurrence":0,"step_id":"tap","phase":"after_postcondition"});let mut other=c.clone();other["occurrence"]=json!(1);assert_ne!(checkpoint_text(&c),checkpoint_text(&other));for (i,cp) in [c,other].into_iter().enumerate(){let text=checkpoint_text(&cp);assert!(text.contains(&format!("execution {}",i+1))&&text.contains("v2"));assert_eq!(cp["occurrence"],i);let row=json!({"checkpoint":cp,"evidence_ref":null,"review":"NOT_REVIEWED","reason":"EVIDENCE_INSUFFICIENT"});assert!(row_text(&row).contains(&text));}assert!(checkpoint_text(&json!({})).contains("execution unknown"));}
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
  assert!(pending);let r=s.exchange("result",json!({})).unwrap();assert_eq!(r["result"]["contract"],"synthetic-observation.v2");assert_eq!(r["result"]["checks"]["before-check"]["routes_with_evidence"],1);assert_eq!(r["result"]["checks"]["after-check"]["routes_with_evidence"],0);for id in ["before-check","after-check"]{assert_eq!(r["result"]["checks"][id]["routes_expected"],2);}let rows=r["result"]["rows"].as_array().unwrap();assert_eq!(rows.len(),4);assert_eq!(rows.iter().filter(|row|row["reason"]=="PLAN_CHECKPOINT_MISSING").count(),2);assert_eq!(rows.iter().filter(|row|row["reason"]=="EVIDENCE_INSUFFICIENT").count(),1);assert_eq!(r["matching_report"]["rows"].as_array().unwrap().len(),4);let id=r["result"]["run_id"].clone();let plan=r["result"]["plan_hash"].clone();drop(s);let mut restarted=session::Session::start_observation().unwrap();let listing=restarted.exchange("history",json!({})).unwrap();assert!(listing["history"].as_array().unwrap().iter().any(|v|v["run_id"]==id&&v["available"]==true));let loaded=restarted.exchange("load_completed",json!({"run_id":id,"plan_hash":plan})).unwrap();assert_eq!(loaded["result"],r["result"]);assert_eq!(loaded["matching_report"],r["matching_report"]);assert_eq!(restarted.exchange("status",json!({})).unwrap()["status"],"idle");
 }
}
