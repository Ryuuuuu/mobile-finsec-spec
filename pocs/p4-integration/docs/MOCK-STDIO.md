# Actual child-process boundary, Python client only

## Decision

MSVC installation/license approval remains deferred. Rust metadata compilation does not produce an executable, and no usable WSL/Docker environment was found. Rather than claim Rust-Python IPC, this POC tests a real Python child process through inherited standard input/output pipes. No native GPUI, Rust client, model, device or assessment skill is executed.

`python -m integration.mock_stdio --mock-root <disposable-private-directory>` creates one synthetic device, one opaque mock item and a StructureSupervisor/StartAPI/UIBridge/UIWire instance. Use a dedicated disposable directory, never a user's skill/project directory. It has no recording registry: an unselected recording carries the existing default app-launch **intent only**, not an actual launch. P1/P2 artifact-to-agent behavior remains separately tested in-process.

## Protocol and lifecycle

The child emits a `mock-stdio.v1` ready JSON line. Each following input line contains one existing `mock-ui-request.v1` JSON request; each output line contains its corresponding response. The tested client permits one outstanding request at a time. JSON newlines must be escaped. The child accepts a maximum 256 KiB payload plus newline; oversized/unterminated frames terminate the input session without treating their tail as another command. Invalid JSON within a valid frame receives UIWire's fixed error.

Input reading runs in a background thread so the asyncio supervisor can progress between commands. Output is protocol-only and flushed. EOF requests cancellation of unfinished jobs and waits up to one second; uncertain cleanup emits recovery_required. A parent must impose its own shutdown deadline because cooperative tasks or blocked pipe writes may still prevent process exit. This worker does not promise OS-level cancellation of external tools.

The process is launched directly without a shell, credentials, network listener or UAC. Inherited pipe ownership replaces the proposed network transport for this **mock experiment only**; it is not the product's authenticated HTTP API or an OS sandbox. Local filesystem access and caller identity remain trusted. A future Rust launcher can use the same protocol only after implementing bounded decoding, deadlines, child lifecycle handling and UI-thread-safe delivery.

An accepted request persists its admission before its reply. After restart, replaying the same command reports recovery_required, even if the earlier job completed. No auto-retry with a new command ID is permitted. This intentionally conservative behavior requires future reconciliation before resuming uncertain work. Finalized result files remain readable after restart; process exit alone never means successful completion.

## Executed tests

Three tests spawn actual child processes using isolated temporary roots:

- Preflight, submit, progress polling, final-result/history lookup, EOF exit code 0, restart, readable final result and prior-command recovery_required.
- Forced child termination after accepted reply, restart and durable refusal to repeat the admission. Whether work finished before termination is intentionally unspecified; this test does not claim mid-item cancellation.
- Unterminated input frame followed by EOF, fixed error, clean child exit and no execution directory created.

The test client imposes a five-second response/process deadline and does not retry requests. Tests clean up their own child processes only. These are actual process/pipe/SQLite persistence tests with synthetic tasks, not simulated subprocess results.

Run `python -m unittest discover -s tests -p test_mock_stdio.py -v` from pocs/p4-integration, or use the current explicit structural runner. Remaining gates: actual Rust-Python communication, native GPUI rendering, concurrent request correlation, slow-reader/backpressure handling, large-frame stress, crash at every storage boundary, authenticated product transport and user-project lifecycle.

Windows/Python 3.12.10 validation: 3 subprocess tests passed; the full explicit structural runner passed 97 tests, zero skips.
