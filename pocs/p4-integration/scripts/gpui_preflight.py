"""Read-only tool discovery; no installs, process launches or device access."""
import json
import shutil


def inspect():
    checks = [{"name": name, "available": shutil.which(name) is not None}
              for name in ("rustc", "cargo", "rustup", "cmake", "cl")]
    missing = [check["name"] for check in checks if not check["available"]]
    return {
        "contract": "gpui-build-preflight.v1",
        "status": "blocked_prerequisites" if missing else "tools_discovered_not_build_verified",
        "checks": checks,
        "missing": missing,
        "compilation": "not_run",
        "native_window": "not_run",
        "note": "Discovery only. Verify versions, MSVC target, C++ workload and SDK before building.",
    }


if __name__ == "__main__":
    report = inspect()
    print(json.dumps(report, indent=2))
    raise SystemExit(2 if report["missing"] else 0)
