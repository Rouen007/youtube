#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Health check for YouTube skill dependencies.

Inspired by Agent-Reach's probe system: checks each tool's availability,
version, and runtime requirements.

Usage:
  python3 doctor.py           # Full check
  python3 doctor.py --json    # JSON output
"""

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class ProbeResult:
    name: str
    status: str  # "ok", "warn", "error", "missing"
    message: str
    version: Optional[str] = None
    fix_hint: Optional[str] = None


def probe_command(binary: str, version_args: list, timeout: int = 10) -> ProbeResult:
    """Probe a command's availability and version."""
    path = shutil.which(binary)
    if not path:
        return ProbeResult(
            name=binary, status="missing",
            message=f"{binary} not found in PATH",
            fix_hint=f"Install: pip install {binary}" if binary in ("yt-dlp",) else f"Install {binary}"
        )

    try:
        proc = subprocess.run(
            [binary] + version_args,
            capture_output=True, text=True, timeout=timeout
        )
        version = (proc.stdout.strip() or proc.stderr.strip()).split('\n')[0]
        if proc.returncode == 0:
            return ProbeResult(name=binary, status="ok", message=f"{binary} available", version=version)
        return ProbeResult(
            name=binary, status="error",
            message=f"{binary} returned exit code {proc.returncode}",
            version=version,
            fix_hint=f"Try reinstalling {binary}"
        )
    except subprocess.TimeoutExpired:
        return ProbeResult(name=binary, status="error", message=f"{binary} timed out")
    except Exception as e:
        return ProbeResult(name=binary, status="error", message=str(e))


def check_js_runtime() -> ProbeResult:
    """Check if a JS runtime is available for yt-dlp YouTube challenges."""
    deno = shutil.which("deno")
    node = shutil.which("node")

    if deno:
        try:
            proc = subprocess.run(["deno", "--version"], capture_output=True, text=True, timeout=5)
            ver = proc.stdout.strip().split('\n')[0] if proc.returncode == 0 else "unknown"
            return ProbeResult(
                name="js-runtime", status="ok",
                message=f"deno available (yt-dlp JS challenges enabled)",
                version=ver
            )
        except Exception:
            pass

    if node:
        try:
            proc = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=5)
            ver = proc.stdout.strip() if proc.returncode == 0 else "unknown"
            return ProbeResult(
                name="js-runtime", status="ok",
                message=f"node available (yt-dlp JS challenges enabled)",
                version=ver
            )
        except Exception:
            pass

    return ProbeResult(
        name="js-runtime", status="error",
        message="No JS runtime found — yt-dlp cannot solve YouTube JS challenges",
        fix_hint="Install deno: brew install deno  (or install Node.js)"
    )


def check_python_package(package: str, import_name: Optional[str] = None) -> ProbeResult:
    """Check if a Python package is importable."""
    mod_name = import_name or package.replace("-", "_")
    try:
        mod = __import__(mod_name)
        ver = getattr(mod, '__version__', 'installed')
        return ProbeResult(name=package, status="ok", message=f"{package} available", version=str(ver))
    except ImportError:
        return ProbeResult(
            name=package, status="missing",
            message=f"{package} not installed",
            fix_hint=f"pip install {package}"
        )


def run_all_checks(as_json: bool = False):
    """Run all health checks."""
    checks = [
        probe_command("yt-dlp", ["--version"]),
        probe_command("ffmpeg", ["-version"]),
        check_js_runtime(),
        check_python_package("youtube_transcript_api"),
        check_python_package("faster_whisper"),
    ]

    if as_json:
        print(json.dumps([asdict(c) for c in checks], ensure_ascii=False, indent=2))
        return

    # Pretty print
    icons = {"ok": "✅", "warn": "⚠️", "error": "❌", "missing": "❌"}
    print("YouTube Skill Health Check")
    print("=" * 50)
    all_ok = True
    for c in checks:
        icon = icons.get(c.status, "?")
        ver = f" ({c.version})" if c.version else ""
        print(f"{icon} {c.name}: {c.message}{ver}")
        if c.fix_hint and c.status != "ok":
            print(f"   💡 {c.fix_hint}")
        if c.status in ("error", "missing"):
            all_ok = False

    print()
    if all_ok:
        print("All core checks passed! ✅")
    else:
        print("Some checks failed. Fix the issues above for best results.")


def main():
    as_json = "--json" in sys.argv
    run_all_checks(as_json)


if __name__ == "__main__":
    main()
