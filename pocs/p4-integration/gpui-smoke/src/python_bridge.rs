//! Read-only, one-shot private child probe. No device/model or task admission.
use std::{io::{Read,Write},path::PathBuf,process::{Command,Stdio},thread,time::{Duration,Instant}};
use serde_json::{Value,json};
const LIMIT:u64=256*1024;
pub fn parse(bytes:&[u8])->Result<usize,&'static str>{
    if bytes.len() as u64>LIMIT{return Err("response limit");}
    let text=std::str::from_utf8(bytes).map_err(|_|"encoding")?;
    let mut lines=text.lines();
    let ready:Value=serde_json::from_str(lines.next().ok_or("missing ready")?).map_err(|_|"ready JSON")?;
    if ready["contract"]!="mock-stdio.v1"||ready["status"]!="ready"||ready["synthetic"]!=true{return Err("ready mismatch");}
    let reply:Value=serde_json::from_str(lines.next().ok_or("missing reply")?).map_err(|_|"reply JSON")?;
    if lines.next().is_some(){return Err("extra frames");}
    if reply["contract"]!="mock-ui.v1"||reply["project_id"]!="synthetic-stdio"||reply["request_generation"].as_u64()!=Some(1){return Err("response identity");}
    reply["runs"].as_array().map(|v|v.len()).ok_or("history unavailable")
}
pub fn probe()->Result<usize,&'static str>{
    let python=std::env::var_os("FINSEC_MOCK_PYTHON").ok_or("configure FINSEC_MOCK_PYTHON")?;
    let root=std::env::var_os("FINSEC_MOCK_ROOT").ok_or("configure FINSEC_MOCK_ROOT")?;
    let project=PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().ok_or("project path")?.to_path_buf();
    let mut command=Command::new(python);
    command.args(["-m","integration.mock_stdio","--mock-root"]).arg(root).current_dir(project).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null());
    #[cfg(windows)] {use std::os::windows::process::CommandExt;command.creation_flags(0x08000000);}
    let mut child=command.spawn().map_err(|_|"child start")?;
    let stdout=child.stdout.take().ok_or("stdout")?;
    let reader=thread::spawn(move||{let mut data=Vec::new();stdout.take(LIMIT+1).read_to_end(&mut data).map(|_|data)});
    let request=json!({"contract":"mock-ui-request.v1","project_id":"synthetic-stdio","request_generation":1,"operation":"history","arguments":{}}).to_string()+"\n";
    let write=child.stdin.take().ok_or("stdin")?.write_all(request.as_bytes());
    if write.is_err(){let _=child.kill();let _=child.wait();let _=reader.join();return Err("request write");}
    let deadline=Instant::now()+Duration::from_secs(5);
    loop {
        match child.try_wait(){
            Ok(Some(status))=>{if !status.success(){let _=reader.join();return Err("child failed");}break;},
            Ok(None) if Instant::now()<deadline=>thread::sleep(Duration::from_millis(20)),
            _=>{let _=child.kill();let _=child.wait();let _=reader.join();return Err("child deadline or wait failure");}
        }
    }
    let bytes=reader.join().map_err(|_|"reader")?.map_err(|_|"read")?;
    parse(&bytes)
}
#[cfg(test)] mod tests{
 use super::*;
 fn message()->Vec<u8>{b"{\"contract\":\"mock-stdio.v1\",\"status\":\"ready\",\"synthetic\":true}\n{\"contract\":\"mock-ui.v1\",\"project_id\":\"synthetic-stdio\",\"request_generation\":1,\"runs\":[]}\n".to_vec()}
 #[test] fn accepted_history(){assert_eq!(parse(&message()),Ok(0));}
 #[test] fn stale_and_malformed_rejected(){let s=String::from_utf8(message()).unwrap();assert!(parse(s.replace("\"request_generation\":1","\"request_generation\":2").as_bytes()).is_err());assert!(parse(b"broken").is_err());let mut extra=message();extra.extend(b"{}\n");assert!(parse(&extra).is_err());assert!(parse(&vec![0;LIMIT as usize+1]).is_err());}
 #[test] #[ignore="requires explicit local Python and disposable mock root"] fn real_python_child(){assert_eq!(probe(),Ok(0));}
}
