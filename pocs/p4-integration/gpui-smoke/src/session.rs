//! Persistent trusted mock child; no shell, network, device or model.
use std::{io::{BufRead,BufReader,Read,Write},path::PathBuf,process::{Child,ChildStdin,Command,Stdio},sync::mpsc::{self,Receiver},thread,time::{Duration,Instant}};
use serde_json::{Value,json};
const LIMIT:usize=256*1024;
pub struct Session {child:Child,input:Option<ChildStdin>,rx:Receiver<Result<Vec<u8>,String>>,generation:u64,poisoned:bool}
impl Session {
 pub fn start()->Result<Self,String>{
  let python=std::env::var_os("FINSEC_MOCK_PYTHON").ok_or("Set FINSEC_MOCK_PYTHON")?;
  let root=std::env::var_os("FINSEC_MOCK_ROOT").ok_or("Set FINSEC_MOCK_ROOT to a disposable synthetic folder")?;
  let cwd=PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().ok_or("project path")?.to_path_buf();
  let mut cmd=Command::new(python);cmd.args(["-m","integration.mock_stdio","--mock-root"]).arg(root).current_dir(cwd).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null());
  #[cfg(windows)] {use std::os::windows::process::CommandExt;cmd.creation_flags(0x08000000);}
  let mut child=cmd.spawn().map_err(|_|"Python start failed")?;let input=child.stdin.take();let stdout=child.stdout.take().unwrap();let(tx,rx)=mpsc::channel();
  thread::spawn(move||{let mut reader=BufReader::new(stdout);loop{let mut line=Vec::new();let read=(&mut reader).take((LIMIT+1) as u64).read_until(b'\n',&mut line);if read.is_err()||line.is_empty()||line.len()>LIMIT||!line.ends_with(b"\n"){let _=tx.send(Err("Child EOF or invalid frame".into()));break;}if tx.send(Ok(line)).is_err(){break;}}});
  let mut s=Self{child,input,rx,generation:0,poisoned:false};let ready=s.receive()?;
  if ready["contract"]!="mock-stdio.v1"||ready["status"]!="ready"||ready["synthetic"]!=true{return Err("Unexpected child readiness".into());}Ok(s)
 }
 fn receive(&mut self)->Result<Value,String>{let bytes=self.rx.recv_timeout(Duration::from_secs(5)).map_err(|_|"Response deadline; outcome unknown".to_string())??;serde_json::from_slice(&bytes).map_err(|_|"Invalid child JSON".into())}
 pub fn exchange(&mut self,op:&str,args:Value)->Result<Value,String>{
  if self.poisoned{return Err("Channel unusable; reconcile before restart".into());}
  self.generation+=1;let msg=json!({"contract":"mock-ui-request.v1","project_id":"synthetic-stdio","request_generation":self.generation,"operation":op,"arguments":args}).to_string()+"\n";
  if msg.len()>LIMIT{return Err("Request limit".into());}
  // Only bounded small built-in UI operations, never arbitrary packet payloads.
  let result=(||{self.input.as_mut().ok_or("Closed input")?.write_all(msg.as_bytes()).map_err(|_|"Request write failed")?;let v=self.receive()?;
   if v["contract"]!="mock-ui.v1"||v["project_id"]!="synthetic-stdio"||v["request_generation"].as_u64()!=Some(self.generation){return Err("Response scope/version mismatch; outcome unknown".into());}Ok(v)})();
  if result.is_err(){self.poisoned=true;let _=self.child.kill();let _=self.child.wait();self.input.take();}result
 }
}
impl Drop for Session {fn drop(&mut self){self.input.take();let until=Instant::now()+Duration::from_secs(1);loop{match self.child.try_wait(){Ok(Some(_))=>break,Ok(None) if Instant::now()<until=>thread::sleep(Duration::from_millis(10)),_=>{let _=self.child.kill();let _=self.child.wait();break;}}}}}
pub fn request(recording:Option<&str>,id:&str)->Value {let mut v=json!({"contract":"structural-start.v1","command_id":id,"device_id":"synthetic-device-p4","platform":"aos","items":["mock-item"],"inventory_revision":1});if let Some(r)=recording{v["recording_ref"]=json!(r);}v}
#[cfg(test)]mod tests{use super::*;
 #[test]fn selected_vs_default_contract(){assert!(request(None,"x").get("recording_ref").is_none());assert_eq!(request(Some("qa"),"x")["recording_ref"],"qa");}
 #[test]#[ignore="requires explicit existing Python and disposable root"]fn actual_three_tab_flow(){let mut s=Session::start().unwrap();assert_eq!(s.exchange("recordings",json!({})).unwrap()["status"],"ok");let id=format!("rust-test-{}",std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos());let r=request(None,&id);assert_eq!(s.exchange("inspect",json!({"request":r})).unwrap()["data"]["enabled"],true);let a=s.exchange("submit",json!({"request":r})).unwrap();let jid=a["data"]["execution_id"].as_str().unwrap();assert_eq!(s.exchange("submit",json!({"request":r})).unwrap()["data"]["execution_id"],jid);let mut events=0;let mut cursor=0;let deadline=Instant::now()+Duration::from_secs(5);let rid=loop{let p=s.exchange("progress",json!({"execution_id":jid,"cursor":cursor})).unwrap();events+=p["events"].as_array().unwrap().len();cursor=p["next_cursor"].as_u64().unwrap();if p["execution"]["status"]=="finished"{break p["run_id"].as_str().unwrap().to_string();}assert!(Instant::now()<deadline);};assert!(events>0);let history=s.exchange("history",json!({})).unwrap();assert!(history["runs"].as_array().unwrap().iter().any(|v|v["run_id"]==rid));let detail=s.exchange("result",json!({"run_id":rid})).unwrap();assert_eq!(detail["status"],"ok");assert!(detail["result"].get("events").is_none());drop(s);let mut again=Session::start().unwrap();assert_eq!(again.exchange("submit",json!({"request":r})).unwrap()["data"]["status"],"recovery_required");assert_eq!(again.exchange("result",json!({"run_id":rid})).unwrap()["status"],"ok");}
 #[test]#[ignore="requires two generated synthetic records"]fn actual_ordered_records_repeat_and_isolation(){let mut s=Session::start().unwrap();let catalog=s.exchange("recordings",json!({})).unwrap();assert_eq!(catalog["recordings"].as_array().unwrap().len(),2);let mut runs=vec![];
 for (index,reference) in ["demo-2","demo-1","demo-2"].iter().enumerate(){let id=format!("queue-{}-{index}",std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos());let r=request(Some(reference),&id);let a=s.exchange("submit",json!({"request":r})).unwrap();assert_eq!(a["data"]["status"],"accepted");let jid=a["data"]["execution_id"].as_str().unwrap();let until=Instant::now()+Duration::from_secs(5);let rid=loop{let p=s.exchange("progress",json!({"execution_id":jid,"cursor":0})).unwrap();if p["execution"]["status"]=="finished"{assert_eq!(p["execution"]["execution_status"],"completed");break p["run_id"].as_str().unwrap().to_string();}assert!(Instant::now()<until);};let result=s.exchange("result",json!({"run_id":rid})).unwrap();assert_eq!(result["result"]["items"][0]["recording_context"]["recording_id"],catalog["recordings"].as_array().unwrap().iter().find(|r|r["ref"]==*reference).unwrap()["recording"]["recording_id"]);assert!(!runs.contains(&rid));runs.push(rid);}
 assert_eq!(runs.len(),3);
 }

}
