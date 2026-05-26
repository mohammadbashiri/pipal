import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .runner import _find_native_pi

SUMMARY_FILE_NAME = "summary.md"
SUMMARY_LOG_NAME = "summary.log"
SUMMARY_STATE_NAME = "summary.state.json"


@dataclass
class SummaryResult:
    status: str
    message: str
    summary_path: Path | None = None


def _log_summary_event(summary_path: Path, message: str) -> None:
    log_path = summary_path.parent / SUMMARY_LOG_NAME
    line = f"[{__import__('datetime').datetime.utcnow().isoformat()}Z] {message}\n"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def _extract_text_parts(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    parts: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and isinstance(part.get("text"), str):
            parts.append(part["text"])
    return parts


def _extract_tool_call_lines(content: Any) -> list[str]:
    if not isinstance(content, list):
        return []
    calls: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") != "toolCall":
            continue
        name = part.get("name")
        if not isinstance(name, str):
            continue
        args = part.get("arguments") or {}
        calls.append(f"Tool {name} called with args {json.dumps(args)}")
    return calls


def _build_conversation_text(entries: Iterable[dict[str, Any]]) -> str:
    sections: list[str] = []
    for entry in entries:
        if entry.get("type") != "message":
            continue
        message = entry.get("message") or {}
        role = message.get("role")
        if role not in {"user", "assistant"}:
            continue
        lines: list[str] = []
        text_parts = _extract_text_parts(message.get("content"))
        if text_parts:
            label = "User" if role == "user" else "Assistant"
            text = "\n".join(text_parts).strip()
            if text:
                lines.append(f"{label}: {text}")
        if role == "assistant":
            lines.extend(_extract_tool_call_lines(message.get("content")))
        if lines:
            sections.append("\n".join(lines))
    return "\n\n".join(sections)


def _parse_session_timestamp(filename: str) -> str:
    match = re.match(r"(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})", filename)
    if not match:
        return filename.replace(".jsonl", "")
    year, month, day, hour, minute, _ = match.groups()
    return f"{year}-{month}-{day} {hour}:{minute}"


def _build_entry_prompt(compaction_summary: str) -> str:
    return "\n".join(
        [
            "Summarize this assistant session in a short paragraph.",
            "Focus on what the user and assistant worked on, decisions made, and anything left open.",
            "Be concise and factual. Do not use headers or bullet points.",
            "If the session contains no meaningful exchange worth recording, respond with exactly: SKIP",
            "",
            "<session_compaction>",
            compaction_summary,
            "</session_compaction>",
        ]
    )


def _load_session_entries(session_file: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line in session_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _load_summary_state(state_path: Path) -> set[str]:
    if not state_path.exists():
        return set()
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    summarized = payload.get("summarized")
    if not isinstance(summarized, list):
        return set()
    return {str(item) for item in summarized if isinstance(item, str)}


def _write_summary_state(state_path: Path, summarized: set[str]) -> None:
    state_path.write_text(
        json.dumps({"summarized": sorted(summarized)}, indent=2) + "\n",
        encoding="utf-8",
    )


def _load_last_entry(session_file: Path) -> dict[str, Any] | None:
    try:
        lines = session_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def _load_last_compaction_summary(session_file: Path) -> str | None:
    entry = _load_last_entry(session_file)
    if not entry or entry.get("type") != "compaction":
        return None
    summary = entry.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return None
    return summary.strip()


def _resolve_latest_session_file(session_dir: Path) -> Path | None:
    if not session_dir.exists():
        return None
    candidates = sorted(session_dir.glob("*.jsonl"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: (p.stat().st_mtime, p.name))


def _resolve_summary_model(llm_config: dict[str, Any]) -> tuple[str | None, str | None]:
    provider = os.getenv("PIPAL_SUMMARY_PROVIDER") or llm_config.get("provider")
    model = os.getenv("PIPAL_SUMMARY_MODEL") or llm_config.get("model")
    return provider, model


def _run_pi_summary(prompt: str, provider: str, model: str) -> str | None:
    pi_bin = _find_native_pi()
    cmd = [
        pi_bin,
        "--provider",
        provider,
        "--model",
        model,
        "--no-extensions",
        "--no-session",
        "-p",
        prompt,
    ]
    result = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
    )
    output = (result.stdout or "").strip()
    if not output and result.stderr:
        output = result.stderr.strip()
    if result.returncode != 0:
        raise RuntimeError(output or "pi summary failed")
    return output


def summarize_session(agent_path: Path, session_name: str | None, llm_config: dict[str, Any]) -> SummaryResult:
    sessions_dir = agent_path / "sessions"
    if not sessions_dir.exists():
        return SummaryResult("SKIP", "No sessions directory")

    session_dir = sessions_dir / (session_name or "main")
    if not session_dir.exists():
        return SummaryResult("SKIP", f"Session not found: {session_dir}")

    session_files = sorted(session_dir.glob("*.jsonl"))
    if not session_files:
        return SummaryResult("SKIP", f"No session files in {session_dir}")

    summary_path = session_dir / SUMMARY_FILE_NAME
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    state_path = session_dir / SUMMARY_STATE_NAME
    summarized = _load_summary_state(state_path)

    pending: list[tuple[str, str]] = []
    for session_file in session_files:
        name = session_file.name
        if name in summarized:
            continue
        compaction_summary = _load_last_compaction_summary(session_file)
        if not compaction_summary:
            continue
        pending.append((name, compaction_summary))

    if not pending:
        _log_summary_event(summary_path, "Summarize skipped (no new compacted sessions)")
        return SummaryResult("SKIP", "No new compacted sessions", summary_path)

    provider, model = _resolve_summary_model(llm_config)
    if not provider or not model:
        _log_summary_event(summary_path, "Summarize skipped (missing provider/model)")
        return SummaryResult("SKIP", "Missing provider/model", summary_path)

    _log_summary_event(
        summary_path,
        f"Summarize start model={provider}/{model} sessions={len(pending)}",
    )

    appended = 0
    for name, compaction_summary in pending:
        prompt = _build_entry_prompt(compaction_summary)
        try:
            entry_text = _run_pi_summary(prompt, provider, model)
        except Exception as exc:
            _log_summary_event(summary_path, f"Summarize failed for {name} error={exc}")
            continue

        if not entry_text or entry_text.strip().upper() == "SKIP":
            _log_summary_event(summary_path, f"Summarize skipped for {name} (no meaningful content)")
            summarized.add(name)
            continue

        ts = _parse_session_timestamp(name)
        entry = f"\n## {ts} | {name}\n{entry_text.strip()}\n"
        with summary_path.open("a", encoding="utf-8") as handle:
            handle.write(entry)

        summarized.add(name)
        appended += 1
        _log_summary_event(summary_path, f"Entry appended for {name} chars={len(entry_text)}")

    _write_summary_state(state_path, summarized)

    if appended == 0:
        return SummaryResult("SKIP", "No entries written", summary_path)

    _log_summary_event(summary_path, f"Summarize complete entries={appended}")
    return SummaryResult("OK", f"summary updated: {summary_path} entries={appended}", summary_path)
