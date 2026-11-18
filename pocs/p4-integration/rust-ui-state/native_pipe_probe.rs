//! Narrow Windows x64 smoke harness; no std/CRT/GPUI/general JSON parser.
#![no_std]
#![no_main]
mod response_guard;
use core::{ffi::c_void, panic::PanicInfo, ptr::null_mut};

#[link(name="kernel32", kind="raw-dylib")]
extern "system" {
    fn GetStdHandle(kind: u32) -> *mut c_void;
    fn ReadFile(handle: *mut c_void, buffer: *mut u8, count: u32, read: *mut u32, overlap: *mut c_void) -> i32;
    fn WriteFile(handle: *mut c_void, buffer: *const u8, count: u32, written: *mut u32, overlap: *mut c_void) -> i32;
    fn ExitProcess(code: u32) -> !;
}

#[panic_handler]
fn panic(_: &PanicInfo) -> ! { unsafe { ExitProcess(90) } }

// LLVM lowers runtime slice equality to this C ABI primitive. Volatile reads
// prevent the standalone implementation being lowered recursively to memcmp.
#[no_mangle]
pub unsafe extern "C" fn memcmp(left: *const c_void, right: *const c_void, count: usize) -> i32 {
    let left=left.cast::<u8>();let right=right.cast::<u8>();
    for offset in 0..count {
        let a=left.add(offset).read_volatile();let b=right.add(offset).read_volatile();
        if a!=b { return a as i32-b as i32; }
    }
    0
}

fn check(ok: bool, code: u32) { if !ok { unsafe { ExitProcess(code) } } }

unsafe fn write(handle: *mut c_void, mut bytes: &[u8]) {
    while !bytes.is_empty() {
        let mut count=0;
        check(WriteFile(handle,bytes.as_ptr(),bytes.len() as u32,&mut count,null_mut())!=0 && count>0,22);
        bytes=&bytes[count as usize..];
    }
}

unsafe fn expect(handle: *mut c_void, expected: &[u8]) {
    // Exact bounded fixture wire comparison, deliberately not a general JSON parser.
    for expected_byte in expected.iter().chain(core::iter::once(&b'\n')) {
        let mut byte=0;let mut count=0;
        check(ReadFile(handle,&mut byte,1,&mut count,null_mut())!=0 && count==1,20);
        check(byte==*expected_byte,21);
    }
}

#[no_mangle]
pub extern "system" fn mainCRTStartup() -> ! {
    fn accepts(ep: &str, eg: u64, er: Option<&str>, c: &str, p: &str, g: u64, r: Option<&str>) -> bool {
        let a=core::hint::black_box((ep,eg,er,c,p,g,r));
        response_guard::accepts(a.0,a.1,a.2,a.3,a.4,a.5,a.6)
    }
    check(accepts("mock",1,Some("new"),"mock-ui.v1","mock",1,Some("new")),10);
    check(!accepts("mock",1,Some("new"),"old","mock",1,Some("new")),11);
    check(!accepts("mock",1,Some("new"),"mock-ui.v1","other",1,Some("new")),12);
    check(!accepts("mock",1,Some("new"),"mock-ui.v1","mock",0,Some("new")),13);
    check(!accepts("mock",1,Some("new"),"mock-ui.v1","mock",1,Some("old")),14);
    check(!accepts("mock",1,Some("new"),"mock-ui.v1","mock",1,None),15);
    unsafe {
        let input=GetStdHandle((-10i32) as u32);let output=GetStdHandle((-11i32) as u32);
        expect(input,br#"{"contract": "mock-stdio.v1", "status": "ready", "synthetic": true}"#);
        write(output,b"{\"contract\":\"mock-ui-request.v1\",\"project_id\":\"synthetic-stdio\",\"request_generation\":1,\"operation\":\"history\",\"arguments\":{}}\n");
        expect(input,br#"{"contract": "mock-ui.v1", "project_id": "synthetic-stdio", "request_generation": 1, "status": "ok", "runs": []}"#);
        write(output,b"{\"contract\":\"mock-ui-request.v1\",\"project_id\":\"wrong-project\",\"request_generation\":1,\"operation\":\"history\",\"arguments\":{}}\n");
        expect(input,br#"{"error":"INVALID_REQUEST_OR_RESPONSE","outcome":"unknown"}"#);
        write(output,b"{\"contract\":\"mock-ui-request.v1\",\"project_id\":\"synthetic-stdio\",\"request_generation\":2,\"operation\":\"history\",\"arguments\":{}}\n");
        expect(input,br#"{"contract": "mock-ui.v1", "project_id": "synthetic-stdio", "request_generation": 2, "status": "ok", "runs": []}"#);
        write(GetStdHandle((-12i32) as u32),b"guard_checks=6;rust_python_roundtrips=3\n");
        ExitProcess(0)
    }
}
