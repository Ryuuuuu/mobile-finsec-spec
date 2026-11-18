"""Separate native smoke gate; no downloads, installs, Cargo or SDK required."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def main():
    if os.name!='nt': raise SystemExit('Windows x64 probe only; not a Linux build.')
    rustc=shutil.which('rustc') or str(Path.home()/'.cargo/bin/rustc.exe')
    sysroot=Path(subprocess.check_output([rustc,'--print','sysroot'],text=True).strip())
    linker=sysroot/'lib/rustlib/x86_64-pc-windows-msvc/bin/rust-lld.exe'
    if not linker.is_file(): raise SystemExit('Existing bundled linker unavailable; no installation attempted.')
    with tempfile.TemporaryDirectory(prefix='p4-native-') as temp:
        exe=Path(temp)/'probe.exe'
        subprocess.run([rustc,'--edition=2021','-C','panic=abort','-C','opt-level=2',
            '-C','lto=fat','-C','codegen-units=1','-C',f'linker={linker}',
            '-C','linker-flavor=lld-link','-C','link-arg=/entry:mainCRTStartup',
            '-C','link-arg=/subsystem:console','-C','link-arg=/nodefaultlib',
            str(ROOT/'rust-ui-state/native_pipe_probe.rs'),'-o',str(exe)],check=True,timeout=60)
        # These are real native exit-code checks, not Rust libtest/Cargo tests.
        for data,expected in ((b'',20),(b'{}\n',21),(b'x'*5000+b'\n',21)):
            result=subprocess.run([str(exe)],input=data,capture_output=True,timeout=5)
            assert result.returncode==expected,(result.returncode,expected)
        server=subprocess.Popen([sys.executable,'-m','integration.mock_stdio',
            '--mock-root',str(Path(temp)/'mock')],cwd=ROOT,stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        client=None
        try:
            # Cross-connect OS pipe handles: Python parent does NOT relay/interpret messages.
            client=subprocess.Popen([str(exe)],stdin=server.stdout,stdout=server.stdin,stderr=subprocess.PIPE)
            _,stderr=client.communicate(timeout=5)
            assert client.returncode==0,client.returncode
            assert stderr==b'guard_checks=6;rust_python_roundtrips=3\n',stderr
            server.stdin.close();server.wait(timeout=5)
            assert server.returncode==0,server.returncode
            assert server.stderr.read()==b''
        finally:
            for process in (client,server):
                if process is not None:
                    if process.poll() is None:process.kill();process.wait(timeout=5)
                    for stream in (process.stdin,process.stdout,process.stderr):
                        if stream is not None and not stream.closed:stream.close()
        print(json.dumps({'native_build':'passed','shared_guard_checks':6,
            'direct_rust_python_roundtrips':3,'native_invalid_input_checks':3,
            'python_exit':0,'gpui':'not_run','rust_libtest':'not_run'}))


if __name__=='__main__':main()
