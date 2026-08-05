from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import shutil
from dataclasses import dataclass
from typing import Iterable

from rich import print
from rich.console import Console

from .llm_config import load_llm_config
from .registry import get_agent, list_agents
from .runner import _find_native_pi
from .server_config import ServerSettings
from .server_rpc import PiRpcClient
from pathlib import Path


REQUIRED_FLAGS = [
    "--mode",
    "--session",
    "--session-dir",
    "--extension",
    "--append-system-prompt",
    "--no-session",
    "--resume",
    "--tools",
]
MIN_PI_VERSION = "0.74.0"

REMEDIATION = {
    "pi binary": [
        "Install pi-coding-agent, then verify it is on PATH: `pi --version`",
    ],
    "pi --version": [
        "Run `pi --version` directly and fix your pi installation/provider setup.",
    ],
    "pi version supported": [
        f"Upgrade pi-coding-agent to at least {MIN_PI_VERSION}.",
        "Then rerun: `pipal check-pi-compatibility`",
    ],
    "pi --help": [
        "Run `pi --help` directly. If it fails, reinstall/update pi-coding-agent.",
    ],
    "required flags": [
        "Update pi-coding-agent to a version that supports pipal's required CLI flags.",
    ],
    "prompt flag": [
        "Your pi build must support `-p` or `--prompt` for one-shot task execution.",
    ],
    "rpc mode": [
        "Your pi build must support `--mode rpc` for `pipal serve` WebSocket chat.",
    ],
    "rpc start": [
        "Ensure at least one agent has `llm.json` (run `pipal agent set-llm <agent> \"provider:model\"`).",
        "If provider auth is missing, open `pi` and complete `/login`.",
    ],
}


@dataclass
class CheckResult:
    name: str
    ok: bool
    details: str


def _run(cmd: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)


def _format_output(proc: subprocess.CompletedProcess) -> str:
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if stdout:
        return stdout
    return stderr


def _check_flag_presence(help_text: str, flags: Iterable[str]) -> list[str]:
    missing: list[str] = []
    for flag in flags:
        if flag not in help_text:
            missing.append(flag)
    return missing


def _check_prompt_flag(help_text: str) -> bool:
    if "--prompt" in help_text:
        return True
    return bool(re.search(r"\s-p[,\s]", help_text))


def _check_rpc_mode(help_text: str) -> bool:
    if "rpc" in help_text.lower():
        return True
    return False


def _extract_semver(value: str) -> tuple[int, int, int] | None:
    match = re.search(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)", value or "")
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _is_version_at_least(current: str, minimum: str) -> bool:
    cur = _extract_semver(current)
    min_v = _extract_semver(minimum)
    if cur is None or min_v is None:
        return False
    return cur >= min_v


async def _run_rpc_check(agent_path: str, llm: dict) -> tuple[bool, str]:
    settings = ServerSettings.load()
    client = PiRpcClient(
        settings=settings,
        agent_dir=Path(agent_path),
        topic_name="doctor",
        llm_config=llm,
        read_only_tools=True,
    )

    previous_autogreet = os.environ.get("PIPAL_DISABLE_AUTOGREET")
    os.environ["PIPAL_DISABLE_AUTOGREET"] = "1"

    try:
        await client.start()
        return True, "RPC started"
    finally:
        await client.close()
        if previous_autogreet is None:
            os.environ.pop("PIPAL_DISABLE_AUTOGREET", None)
        else:
            os.environ["PIPAL_DISABLE_AUTOGREET"] = previous_autogreet


def _select_agent(agent_name: str | None) -> tuple[str, str, dict] | None:
    if agent_name:
        agent = get_agent(agent_name)
        if not agent:
            return None
        llm = load_llm_config(agent["path"])
        if not llm:
            return None
        return agent["name"], agent["path"], llm

    for name, path in list_agents().items():
        llm = load_llm_config(path)
        if llm:
            return name, path, llm
    return None


def _resolve_windows_pi(pi_bin: str) -> str:
    if os.name != "nt":
        return pi_bin
    lower = pi_bin.lower()
    if lower.endswith((".cmd", ".exe", ".bat")):
        return pi_bin
    for ext in (".cmd", ".exe", ".bat"):
        candidate = pi_bin + ext
        if os.path.exists(candidate):
            return candidate
    for name in ("pi.cmd", "pi.exe", "pi.bat", "pi"):
        found = shutil.which(name)
        if found:
            return found
    return pi_bin


def run_doctor(agent_name: str | None = None) -> int:
    results: list[CheckResult] = []
    skip_runtime = os.getenv("PIPAL_DOCTOR_SKIP_RUNTIME") == "1"
    console = Console()

    def _supports_unicode() -> bool:
        encoding = (getattr(sys.stdout, "encoding", None) or "").lower()
        if not encoding:
            return True
        try:
            "→✓✗".encode(encoding)
            return True
        except Exception:
            return False

    unicode_ok = _supports_unicode()
    arrow = "→" if unicode_ok else "->"
    check = "✓" if unicode_ok else "OK"
    cross = "✗" if unicode_ok else "FAIL"

    def log_start(label: str) -> None:
        console.print(f"[cyan]{arrow} {label}...[/cyan]", end="\r")

    def log_result(result: CheckResult) -> None:
        color = "green" if result.ok else "red"
        symbol = check if result.ok else cross
        line = f"[{color}]{symbol} {result.name}: {result.details}[/{color}]"
        console.print(f"{line}          ")

    def print_remediation(result: CheckResult) -> None:
        if result.ok:
            return
        tips = REMEDIATION.get(result.name, [])
        if not tips:
            return
        console.print("[yellow]Suggested fix:[/yellow]")
        for tip in tips:
            console.print(f"  - {tip}")

    log_start("locate pi")
    try:
        pi_bin = _find_native_pi()
    except FileNotFoundError as exc:
        result = CheckResult("pi binary", False, str(exc))
        results.append(result)
        log_result(result)
        print_remediation(result)
        return 2

    pi_bin = _resolve_windows_pi(pi_bin)
    result = CheckResult("pi binary", True, pi_bin)
    results.append(result)
    log_result(result)

    log_start("pi --version")
    version_proc = _run([pi_bin, "--version"])
    if version_proc.returncode != 0:
        result = CheckResult(
            "pi --version",
            False,
            _format_output(version_proc) or f"Exit {version_proc.returncode}",
        )
    else:
        result = CheckResult("pi --version", True, _format_output(version_proc))
    results.append(result)
    log_result(result)
    print_remediation(result)
    if result.ok:
        version_supported = _is_version_at_least(result.details, MIN_PI_VERSION)
        version_result = CheckResult(
            "pi version supported",
            version_supported,
            f"Detected {result.details}; minimum supported is {MIN_PI_VERSION}",
        )
        results.append(version_result)
        log_result(version_result)
        print_remediation(version_result)
        if not version_supported:
            return 2

    log_start("pi --help")
    help_proc = _run([pi_bin, "--help"])
    help_text = _format_output(help_proc)
    if help_proc.returncode != 0 or not help_text:
        result = CheckResult(
            "pi --help",
            False,
            help_text or f"Exit {help_proc.returncode}",
        )
        results.append(result)
        log_result(result)
        print_remediation(result)
        return 2

    log_start("required flags")
    missing_flags = _check_flag_presence(help_text, REQUIRED_FLAGS)
    if missing_flags:
        result = CheckResult(
            "required flags",
            False,
            "Missing: " + ", ".join(missing_flags),
        )
    else:
        result = CheckResult("required flags", True, "All present")
    results.append(result)
    log_result(result)
    print_remediation(result)

    log_start("prompt flag")
    result = CheckResult("prompt flag", _check_prompt_flag(help_text), "-p/--prompt found" if _check_prompt_flag(help_text) else "-p/--prompt missing")
    results.append(result)
    log_result(result)
    print_remediation(result)

    log_start("rpc mode")
    result = CheckResult("rpc mode", _check_rpc_mode(help_text), "rpc mentioned in help" if _check_rpc_mode(help_text) else "rpc not found in help")
    results.append(result)
    log_result(result)
    print_remediation(result)

    if skip_runtime:
        result = CheckResult("rpc start", True, "Skipped (PIPAL_DOCTOR_SKIP_RUNTIME=1)")
        results.append(result)
        log_result(result)
        print_remediation(result)
    else:
        agent_info = _select_agent(agent_name)
        if not agent_info:
            result = CheckResult(
                "rpc start",
                False,
                "No agent with llm.json found. Run: pipal agent set-llm <agent> \"provider:model\"",
            )
            results.append(result)
            log_result(result)
            print_remediation(result)
            return 2

        agent_name, agent_path, llm = agent_info
        log_start("rpc start")
        try:
            ok, details = asyncio.run(_run_rpc_check(agent_path, llm))
            result = CheckResult("rpc start", ok, details)
        except Exception as exc:
            result = CheckResult("rpc start", False, f"Exception: {exc}")
        results.append(result)
        log_result(result)
        print_remediation(result)

    if any(not result.ok for result in results):
        console.print("\n[red]Compatibility check failed.[/red] Resolve the failed checks and rerun:")
        console.print("  [bold]pipal check-pi-compatibility[/bold]")
        return 2
    console.print("\n[green]Compatibility check passed.[/green]")
    return 0
