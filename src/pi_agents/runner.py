import os
import shutil
import sys
import subprocess
from pathlib import Path


PERSONA_FILES = [
    "AGENTS.md",
    "IDENTITY.md",
    "POLICY.md",
    "USER.md",
    "MEMORY.md",
]

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
        "(npm install -g @mariozechner/pi-coding-agent)"
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


def load_persona(agent_path: str) -> str:
    """Read persona markdown files and concatenate into a system prompt."""
    files = [Path(agent_path) / fname for fname in PERSONA_FILES]
    return _load_files(files)


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


EXTENSION_PATH = Path(__file__).resolve().parent / "extensions" / "auto_greet.ts"


def _build_pi_cmd(
    agent_path: str,
    llm_config: dict,
    extra_args: list[str],
    no_session: bool,
    session_name: str,
    system_prompt: str | None,
    include_extension: bool = True,
) -> list[str]:
    cmd = ["pi"]

    if include_extension and EXTENSION_PATH.exists():
        cmd += ["--extension", str(EXTENSION_PATH)]

    provider = llm_config.get("provider")
    model = llm_config.get("model")
    if provider:
        cmd += ["--provider", provider]
    if model:
        cmd += ["--model", model]

    agent = Path(agent_path)
    if no_session:
        cmd.append("--no-session")
    else:
        # Named session file per agent
        sessions_dir = agent / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        session_file = sessions_dir / f"{session_name}.jsonl"
        cmd += ["--session", str(session_file.resolve())]

        # Continue if session already exists
        if session_file.exists():
            cmd.append("-c")

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
):
    cmd = _build_pi_cmd(
        agent_path=agent_path,
        llm_config=llm_config,
        extra_args=extra_args,
        no_session=no_session,
        session_name=session_name,
        system_prompt=system_prompt,
    )

    os.environ["PAL_AGENT_DIR"] = str(Path(agent_path).resolve())
    pi_bin = _find_native_pi()
    os.execv(pi_bin, cmd)


def run_agent(agent_path: str, llm_config: dict, extra_args: list[str]):
    """Invoke pi with persona context, passing through any extra CLI args."""
    # Extract our flags before passing to pi
    session_name, extra_args = _extract_session_name(extra_args)
    heartbeat_only = "--heartbeat-only" in extra_args
    routine_only = "--routine-only" in extra_args
    no_session = "--no-session" in extra_args
    extra_args = [
        a for a in extra_args
        if a not in {"--heartbeat-only", "--routine-only", "--no-session"}
    ]
    if heartbeat_only or routine_only:
        no_session = True

    agent = Path(agent_path)

    # Append persona context to the system prompt (kept out of chat log)
    if heartbeat_only:
        system_prompt = _load_files(_heartbeat_files(agent))
    elif routine_only:
        system_prompt = _load_files([agent / fname for fname in ROUTINE_CONTEXT_FILES])
    else:
        system_prompt = load_persona(agent_path)

    _run_agent_cmd(
        agent_path=agent_path,
        llm_config=llm_config,
        extra_args=extra_args,
        no_session=no_session,
        session_name=session_name,
        system_prompt=system_prompt,
    )


def run_agent_custom_prompt(
    agent_path: str,
    llm_config: dict,
    extra_args: list[str],
    system_prompt: str,
    no_session: bool = True,
    session_name: str = "main",
    disable_autogreet: bool = False,
    start_prompt: str | None = None,
):
    """Invoke pi with a custom system prompt."""
    session_name, extra_args = _extract_session_name(extra_args)
    if "--no-session" in extra_args:
        no_session = True
        extra_args = [a for a in extra_args if a != "--no-session"]

    if start_prompt:
        os.environ["PAL_TASK_START_PROMPT"] = start_prompt
    if disable_autogreet:
        os.environ["PAL_DISABLE_AUTOGREET"] = "1"

    _run_agent_cmd(
        agent_path=agent_path,
        llm_config=llm_config,
        extra_args=extra_args,
        no_session=no_session,
        session_name=session_name,
        system_prompt=system_prompt,
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

    cmd = _build_pi_cmd(
        agent_path=agent_path,
        llm_config=llm_config,
        extra_args=["-p", prompt],
        no_session=no_session,
        session_name=session_name,
        system_prompt=system_prompt,
        include_extension=True,
    )

    env = os.environ.copy()
    env["PAL_AGENT_DIR"] = str(agent.resolve())
    env["PAL_DISABLE_AUTOGREET"] = "1"

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
