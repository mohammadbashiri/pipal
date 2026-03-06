import os
import shutil
import sys
from pathlib import Path


PERSONA_FILES = [
    "identity.md",
    "principles.md",
    "strategy.md",
    "memory.md",
    "reflection.md",
    "heartbeat.md",
]

ROUTINE_CONTEXT_FILES = [
    "identity.md",
    "principles.md",
    "strategy.md",
    "memory.md",
    "reflection.md",
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
        "Could not find the native pi binary. Is pi-mono installed? "
        "(npm install -g @anthropics/pi-coding-agent)"
    )


def load_persona(agent_path: str) -> str:
    """Read persona markdown files and concatenate into a system prompt."""
    parts = []
    for fname in PERSONA_FILES:
        fp = Path(agent_path) / fname
        if fp.exists():
            content = fp.read_text(encoding="utf-8").strip()
            if content:
                parts.append(content)
    return "\n\n---\n\n".join(parts)


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

    cmd = ["pi"]

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

    # Inject persona files via @file syntax
    if heartbeat_only:
        files_to_inject = _heartbeat_files(agent)
    elif routine_only:
        files_to_inject = [agent / fname for fname in ROUTINE_CONTEXT_FILES]
    else:
        files_to_inject = [agent / fname for fname in PERSONA_FILES]

    for fp in files_to_inject:
        if fp.exists():
            content = fp.read_text(encoding="utf-8").strip()
            if content:
                cmd.append(f"@{fp.resolve()}")

    # Pass through all remaining user args (prompts, flags, etc.)
    cmd += extra_args

    pi_bin = _find_native_pi()
    os.execv(pi_bin, cmd)
