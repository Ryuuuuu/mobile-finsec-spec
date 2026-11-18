# Actual native Rust-Python pipe smoke gate without new installation

## Available route and decision

The installed official Rust 1.100.0 x86_64 MSVC toolchain already includes rust-lld.exe. No usable WSL distribution, Docker command or general cloud/Linux execution tool was available; no unknown SSH host was contacted. No installer, target download, PATH/security setting change, MSVC license acceptance or UAC was used for this work.

Rust's [raw-dylib mechanism](https://doc.rust-lang.org/reference/items/external-blocks.html) generates Windows import libraries, and its [linker options](https://doc.rust-lang.org/rustc/codegen-options/index.html) allow selecting the bundled LLVM linker. A narrow no_std executable can therefore call the installed Windows kernel32 API without requiring Visual Studio SDK import libraries or a C runtime. This is a test harness approach, not a replacement GPUI build toolchain.

## What actually ran

`scripts/verify_rust_pipe.py` builds `rust-ui-state/native_pipe_probe.rs` in a private temporary directory with the existing rustc/rust-lld, then executes the resulting native Windows binary. It uses panic=abort, fat LTO, one codegen unit and an explicit console entry point; default C runtime libraries are disabled. Initial non-LTO linking exposed unused core/CRT dependencies; LTO removes those dependencies. Runtime string comparison still requires a small C-ABI memcmp implementation in the harness, using volatile byte reads to avoid recursive lowering. No replacement DLL/runtime is installed.

The allocation-free identity predicate moved into `response_guard.rs`, and the existing std-based Selection wrapper now calls it. The native harness tests this same source: matching identity accepted; wrong contract, project, generation, selected run and absent run rejected. Inputs pass through black_box so these are runtime checks rather than solely constant-folded assertions. The Selection wrapper's tab/generation-overflow tests remain metadata-only; full Rust libtest/Cargo tests were not executed.

The Python test launcher cross-connects the native Rust executable's standard handles directly to a separate existing Python mock_stdio worker. The parent does not forward or translate JSON. Rust reads bootstrap, requests empty history, receives wrong-project rejection, and requests history with a new generation. It compares the exact expected bounded fixture wire responses and reports 6 guard checks / 3 successful round trips via stderr. Both children exit 0 after EOF shutdown. Three additional native runs reject input EOF, malformed bootstrap and a long invalid prefix with expected nonzero codes.

Windows [GetStdHandle](https://learn.microsoft.com/en-us/windows/console/getstdhandle), [ReadFile](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-readfile) and [WriteFile](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-writefile) provide inherited pipe I/O. Reads consume only the expected fixture length; writes handle partial completion. Parent-side five-second process deadlines and cleanup bound hung probe runs. The Rust probe does not implement its own asynchronous cancellation or a general JSON decoder.

## Reproduce and limits

From repository root, using the prepared Python environment:

```text
python pocs/p4-integration/scripts/verify_rust_pipe.py
```

This is a separate native gate from `run_structure_tests.py`. Output reports native build, six shared-guard checks, three direct Rust-Python round trips and three invalid-input checks. Temporary executable/PDB/fixtures are removed; no binary, device capture or private evidence is committed.

This now establishes **limited real Rust-Python pipe communication on Windows**. It does not establish Rust HTTP/bootstrap authentication, full start/record/replay workflows from Rust, JSON compatibility beyond these exact fixture messages, a production unsafe-FFI layer, std/Cargo application linking, GPUI dependencies/rendering, Linux compilation, a real model or a device. No inspection skills or judgement logic were added. The existing MSVC/SDK approval blocker remains for the planned normal GPUI build.
