import os
import shutil
import sys
import subprocess
from datetime import datetime
from pathlib import Path
from uuid import uuid4


PERSONA_FILES = [
    "AGENTS.md",
    "IDENTITY.md",
    "POLICY.md",
    "USER.md",
    "MEMORY.md",
    "KB.md",
]

ONBOARDING_FILE = "onboarding.md"

ROUTINE_CONTEXT_FILES = [
    "IDENTITY.md",
    "POLICY.md",
    "MEMORY.md",
]

def _heartbeat_files(agent: Path) -> list[Path]:
    """Return heartbeat context files, including routine definitions."""
    files: list[Path] = []

    hb = agent / "heartbeat.md"
    if hb.exists():
        files.append(hb)

    routines_dir = agent / "routines"
    if routines_dir.exists():
        files.extend(sorted(
            p for p in routines_dir.glob("*.md") if p.is_file()
        ))

    return files


def _find_native_pi() -> str:
    """Find the real pi-mono binary, skipping our own venv's pi wrapper."""
    # Get the venv bin dir to exclude it from search
    venv_bin = os.path.dirname(sys.executable)

    for d in os.environ.get("PATH", "").split(os.pathsep):
        if os.path.realpath(d) == os.path.realpath(venv_bin):
            continue
        candidate = os.path.join(d, "pi")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    raise FileNotFoundError(
        "Could not find the native pi binary. Is pi installed? "
        "(npm install -g @earendil-works/pi-coding-agent)"
    )


def _load_files(files: list[Path]) -> str:
    """Read markdown files and concatenate into a system prompt."""
    parts = []
    for fp in files:
        if fp.exists():
            content = fp.read_text(encoding="utf-8").strip()
            if content:
                parts.append(content)
    return "\n\n---\n\n".join(parts)


def _resolve_init_marker(agent: Path) -> Path:
    new_marker = agent / ".pipal_initialized"
    old_marker = agent / ".pal_initialized"
    if new_marker.exists():
        return new_marker
    if old_marker.exists():
        return old_marker
    return new_marker


def _onboarding_complete(agent: Path) -> bool:
    onboarding_path = agent / ONBOARDING_FILE
    if not onboarding_path.exists():
        return _resolve_init_marker(agent).exists()
    try:
        content = onboarding_path.read_text(encoding="utf-8")
    except OSError:
        return False
    return "- [ ]" not in content


def load_persona(agent_path: str) -> str:
    """Read persona markdown files and concatenate into a system prompt."""
    agent = Path(agent_path)
    files = [agent / fname for fname in PERSONA_FILES]
    agent_type = _read_agent_type(agent)
    if agent_type != "kbchat" and not _onboarding_complete(agent):
        files.append(agent / ONBOARDING_FILE)
    return _load_files(files)


def _load_summary(agent: Path, session_name: str) -> str:
    summary_path = agent / "sessions" / session_name / "summary.md"
    if not summary_path.exists():
        return ""
    try:
        return summary_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _read_agent_type(agent: Path) -> str | None:
    type_path = agent / ".pipal_type"
    if not type_path.exists():
        return None
    try:
        return type_path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _strip_tool_flags(args: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--tools" and i + 1 < len(args):
            i += 2
            continue
        if args[i] == "--no-tools":
            i += 1
            continue
        out.append(args[i])
        i += 1
    return out


def _extract_session_name(args: list[str]) -> tuple[str, list[str]]:
    """Extract --session <name> from args. Returns (session_name, remaining_args)."""
    remaining = []
    session_name = "main"
    i = 0
    while i < len(args):
        if args[i] == "--session" and i + 1 < len(args):
            session_name = args[i + 1]
            i += 2
        else:
            remaining.append(args[i])
            i += 1
    return session_name, remaining


DEFAULT_EXTENSIONS = [
    Path(__file__).resolve().parent / "extensions" / "rolling_summary.ts",
    Path(__file__).resolve().parent / "extensions" / "auto_greet.ts",
]


def _extension_paths(agent_type: str | None) -> list[Path]:
    if agent_type == "kbchat":
        return [Path(__file__).resolve().parent / "extensions" / "kbchat_greet.ts"]
    return DEFAULT_EXTENSIONS


def _build_pi_cmd(
    agent_path: str,
    llm_config: dict,
    extra_args: list[str],
    no_session: bool,
    session_name: str,
    system_prompt: str | None,
    include_extension: bool = True,
    resume: bool = False,
    extensions: list[Path] | None = None,
) -> list[str]:
    cmd = ["pi"]

    if include_extension:
        extension_paths = extensions if extensions is not None else DEFAULT_EXTENSIONS
        for extension_path in extension_paths:
            if extension_path.exists():
                cmd += ["--extension", str(extension_path)]

    provider = llm_config.get("provider")
    model = llm_config.get("model")
    if provider:
        cmd += ["--provider", provider]
    if model:
        cmd += ["--model", model]

    agent = Path(agent_path)
    if no_session:
        cmd.append("--no-session")
    elif not resume:
        # Folder-based sessions: new file per launch
        sessions_dir = agent / "sessions" / session_name
        sessions_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        session_file = sessions_dir / f"{ts}_{uuid4().hex[:8]}.jsonl"
        cmd += ["--session", str(session_file.resolve())]

    # Append persona context to the system prompt (kept out of chat log)
    if system_prompt:
        cmd += ["--append-system-prompt", system_prompt]

    # Pass through all remaining user args (prompts, flags, etc.)
    cmd += extra_args

    return cmd


def _run_agent_cmd(
    agent_path: str,
    llm_config: dict,
    extra_args: list[str],
    system_prompt: str,
    no_session: bool,
    session_name: str,
    resume: bool,
    extensions: list[Path] | None = None,
):
    cmd = _build_pi_cmd(
        agent_path=agent_path,
        llm_config=llm_config,
        extra_args=extra_args,
        no_session=no_session,
        session_name=session_name,
        system_prompt=system_prompt,
        resume=resume,
        extensions=extensions,
    )

    os.environ["PIPAL_AGENT_DIR"] = str(Path(agent_path).resolve())
    pi_bin = _find_native_pi()
    os.execv(pi_bin, cmd)


def run_agent(agent_path: str, llm_config: dict, extra_args: list[str]):
    """Invoke pi with persona context, passing through any extra CLI args."""
    # Extract our flags before passing to pi
    session_name, extra_args = _extract_session_name(extra_args)
    heartbeat_only = "--heartbeat-only" in extra_args
    routine_only = "--routine-only" in extra_args
    no_session = "--no-session" in extra_args
    resume = "--resume" in extra_args
    extra_args = [
        a for a in extra_args
        if a not in {"--heartbeat-only", "--routine-only", "--no-session"}
    ]
    if heartbeat_only or routine_only:
        no_session = True

    agent = Path(agent_path)

    agent_type = _read_agent_type(agent)
    if agent_type == "kbchat":
        extra_args = _strip_tool_flags(extra_args)
        extra_args += ["--tools", "read,grep,find,ls"]

    if resume and not no_session:
        sessions_dir = agent / "sessions" / session_name
        sessions_dir.mkdir(parents=True, exist_ok=True)
        if "--session-dir" not in extra_args:
            extra_args += ["--session-dir", str(sessions_dir.resolve())]

    # Append persona context to the system prompt (kept out of chat log)
    if heartbeat_only:
        system_prompt = _load_files(_heartbeat_files(agent))
    elif routine_only:
        system_prompt = _load_files([agent / fname for fname in ROUTINE_CONTEXT_FILES])
    else:
        system_prompt = load_persona(agent_path)

    if not no_session:
        summary = _load_summary(agent, session_name)
        if summary:
            summary_block = (
                "Rolling summary (supplemental; core files are authoritative if conflicts):\n"
                f"{summary}"
            )
            if system_prompt:
                system_prompt = f"{system_prompt}\n\n---\n\n{summary_block}"
            else:
                system_prompt = summary_block

    _run_agent_cmd(
        agent_path=agent_path,
        llm_config=llm_config,
        extra_args=extra_args,
        no_session=no_session,
        session_name=session_name,
        system_prompt=system_prompt,
        resume=resume,
        extensions=_extension_paths(agent_type),
    )




def run_agent_print(
    agent_path: str,
    llm_config: dict,
    prompt: str,
    no_session: bool = True,
    session_name: str = "main",
) -> str:
    """Run pi in print mode and return the assistant response."""
    agent = Path(agent_path)
    system_prompt = load_persona(agent_path)

    extra_args = ["-p", prompt]
    agent_type = _read_agent_type(agent)
    if agent_type == "kbchat":
        extra_args = _strip_tool_flags(extra_args)
        extra_args += ["--tools", "read,grep,find,ls"]

    cmd = _build_pi_cmd(
        agent_path=agent_path,
        llm_config=llm_config,
        extra_args=extra_args,
        no_session=no_session,
        session_name=session_name,
        system_prompt=system_prompt,
        include_extension=True,
        extensions=_extension_paths(agent_type),
    )

    env = os.environ.copy()
    env["PIPAL_AGENT_DIR"] = str(agent.resolve())
    env["PIPAL_DISABLE_AUTOGREET"] = "1"

    pi_bin = _find_native_pi()
    result = subprocess.run(
        [pi_bin, *cmd[1:]],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    output = (result.stdout or "").strip()
    if not output and result.stderr:
        output = result.stderr.strip()
    return output
