import fcntl
import os
import shutil
import sys
import subprocess
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .topic_storage import topic_sessions_dir, validate_topic_name


PERSONA_FILES = [
    "AGENTS.md",
    "IDENTITY.md",
    "POLICY.md",
    "USER.md",
    "MEMORY.md",
    "KB.md",
]

ONBOARDING_FILE = "onboarding.md"

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


PIPAL_CONTEXT_TEMPLATE = """\
# You are a pipal agent

pipal is a persistence layer on top of pi. Your home is {agent_home}/.

Topics live under topics/<name>/. Each topic contains native Pi JSONL sessions under sessions/ and may have an optional summary.md.

Current topic: {topic_name}

Conversation history and summaries are consulted on demand, not automatically loaded. For prior-context questions, look in {agent_home}/topics/{topic_name}/summary.md when it exists, and consult the native session files in {agent_home}/topics/{topic_name}/sessions/ for missing details or newer activity. Read the relevant evidence before claiming to remember it; native session history is authoritative.

`/pipal:summary` is simply a shortcut asking you to summarize the current conversation in chat. It does not compact, save files, or start a separate summarizer. Summary persistence is ordinary file editing with the owner's agreement. You may naturally offer to save a useful summary, but there is no mandatory question, wording, or confirmation ritual. Do not treat asking for a summary as permission to save it. Preserve existing topic notes when editing summary.md. Identify saved coverage by source session filename and the branch entry ID or timestamp it covers; a resumed session can contain newer, unsummarized activity. Legacy summary.state.json and summary.log are historical artifacts, not reliable current coverage indexes. Quitting does not summarize or ask about saving.

Pipal TUI commands are namespaced: /pipal:summary, /pipal:delegations, /pipal:delegation <id> [brief|review|audit|watch|join|cancel], and /pipal:detach. Team rooms additionally provide /pipal:team stop. Without an action, /pipal:delegation <id> shows status and available actions. Delegation reports concern delegated work, not summaries of this conversation. Anything else you want to know about pipal or your own state, look around your home.

Live Pipal sessions are discoverable through pipal_session_list (or `pipal live list --json`). Native session UUIDs and @session:<full UUID> references address exact conversations, not agent identities; labels may collide or change. Use pipal_session_start to create a normal handoff-capable conversation or safely resume a closed one, pipal_session_message to contact an existing runtime, and pipal_session_result to retrieve an attributed reply. Busy recipients queue messages without interruption. A queued acknowledgement is not a completed answer. Retain request IDs; on ambiguous delivery or disconnect, check results rather than resending. Leading @session:UUID messages are direct session messages; mentions elsewhere are references for you to act on when appropriate. Native history remains with its sole live Pi process; never open a second writer. Pipal-owned started sessions can be attached with `pipal live attach <id>` for human handoff. Quit is graceful and refuses active or queued work; do not close someone else's session without explicit owner approval. Receiving a peer message is not fresh owner approval, and your normal answer is returned automatically without messaging back. Ordinary sessions have no dependency on Pi App or Telegram for discovery or communication.

Persistent direct/delegation threads with other registered Pipal agents live under topics/{topic_name}/delegations/<agent>/. Use `pipal_delegate` for one agent and `pipal_delegate_team` for a saved team. For a bounded one-off Pipal worker, use `pipal_delegate_ephemeral` and follow up by delegation ID; it defaults to the provider/model selected when this chat started unless explicitly specified. When the owner says "ephemeral agent" in a Pipal delegation context, use this Pipal tool, not Pi's separate `subagent` tool, unless they specifically ask for Pi subagents. Hold multi-turn threads and own delegated outcomes; do not act as a one-shot relay. Normal primary-agent chat is the default entry point. Keep detailed coordination compact unless the owner asks to watch or join it."""


def build_pipal_context(agent: Path, topic_name: str) -> str:
    """Runtime-injected system context block teaching the agent about pipal."""
    return PIPAL_CONTEXT_TEMPLATE.format(
        agent_home=agent.resolve(),
        topic_name=topic_name,
    )


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


def _extract_topic_name(args: list[str]) -> tuple[str, list[str]]:
    """Extract --topic <name> from args. Returns (topic_name, remaining_args)."""
    remaining = []
    topic_name = "main"
    i = 0
    while i < len(args):
        if args[i] == "--topic" and i + 1 < len(args):
            topic_name = args[i + 1]
            i += 2
        else:
            remaining.append(args[i])
            i += 1
    return validate_topic_name(topic_name), remaining


DEFAULT_EXTENSIONS = [
    Path(__file__).resolve().parent / "extensions" / "commands.ts",
    Path(__file__).resolve().parent / "extensions" / "auto_greet.ts",
    Path(__file__).resolve().parent / "extensions" / "delegation.ts",
]


def _extension_paths(agent_type: str | None) -> list[Path]:
    if agent_type == "kbchat":
        return [DEFAULT_EXTENSIONS[0], Path(__file__).resolve().parent / "extensions" / "kbchat_greet.ts"]
    return DEFAULT_EXTENSIONS


def _session_llm_config(saved: dict, extra_args: list[str]) -> dict:
    """Mirror the provider/model flags passed to Pi, without changing llm.json."""
    selected = dict(saved)
    for index, arg in enumerate(extra_args):
        for name in ("provider", "model"):
            if arg == f"--{name}" and index + 1 < len(extra_args):
                selected[name] = extra_args[index + 1]
            elif arg.startswith(f"--{name}="):
                selected[name] = arg.partition("=")[2]
    return selected


def _build_pi_cmd(
    agent_path: str,
    llm_config: dict,
    extra_args: list[str],
    no_session: bool,
    topic_name: str,
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
    elif not resume and "--session" not in extra_args and "--session-id" not in extra_args:
        # A topic spans multiple native pi sessions; create one file per launch.
        sessions_dir = topic_sessions_dir(agent, topic_name)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        session_file = sessions_dir / f"{ts}_{uuid4().hex[:8]}.jsonl"
        cmd += ["--session", str(session_file.resolve())]

    # Append persona context to the system prompt (kept out of chat log)
    if system_prompt:
        cmd += ["--append-system-prompt", system_prompt]

    # Pass through all remaining user args (prompts, flags, etc.)
    cmd += extra_args

    return cmd


def _lock_session_for_exec(cmd: list[str]) -> int | None:
    """Hold an advisory lock through exec so two Pipal TUIs cannot share a JSONL file."""
    session = next((cmd[i + 1] for i, arg in enumerate(cmd[:-1]) if arg == "--session"), None)
    if session is None:
        session = next((arg.partition("=")[2] for arg in cmd if arg.startswith("--session=")), None)
    if not session:
        return None
    lock_path = Path(session).resolve().with_suffix(".jsonl.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.set_inheritable(fd, True)
    except BlockingIOError:
        os.close(fd)
        print(f"This Pi session is already active: {session}. Quit it before resuming.", file=sys.stderr)
        raise SystemExit(2)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _run_agent_cmd(
    agent_path: str,
    llm_config: dict,
    extra_args: list[str],
    system_prompt: str,
    no_session: bool,
    topic_name: str,
    resume: bool,
    extensions: list[Path] | None = None,
):
    cmd = _build_pi_cmd(
        agent_path=agent_path,
        llm_config=llm_config,
        extra_args=extra_args,
        no_session=no_session,
        topic_name=topic_name,
        system_prompt=system_prompt,
        resume=resume,
        extensions=extensions,
    )

    os.environ["PIPAL_AGENT_DIR"] = str(Path(agent_path).resolve())
    os.environ["PIPAL_TOPIC"] = topic_name
    pi_bin = _find_native_pi()
    lock_fd = _lock_session_for_exec(cmd)
    try:
        os.execv(pi_bin, cmd)
    finally:
        if lock_fd is not None:
            os.close(lock_fd)


def run_agent(agent_path: str, llm_config: dict, extra_args: list[str]):
    """Invoke Pi using its defaults or saved session model and explicit CLI flags.

    The legacy llm_config argument is accepted for caller compatibility, but
    interactive launches must not override Pi with agent-specific defaults.
    """
    llm_config = {}
    # Extract Pipal flags before passing the rest to pi.
    topic_name, extra_args = _extract_topic_name(extra_args)
    no_session = "--no-session" in extra_args
    resume = "--resume" in extra_args or "-r" in extra_args
    continue_recent = "--continue" in extra_args or "-c" in extra_args
    extra_args = [a for a in extra_args if a != "--no-session"]

    agent = Path(agent_path)

    agent_type = _read_agent_type(agent)
    if agent_type == "kbchat":
        extra_args = _strip_tool_flags(extra_args)
        extra_args += ["--tools", "read,grep,find,ls"]

    if continue_recent and not no_session:
        sessions_dir = topic_sessions_dir(agent, topic_name)
        extra_args = [arg for arg in extra_args if arg not in {"--continue", "-c"}]
        candidates = list(sessions_dir.glob("*.jsonl"))
        if candidates:
            latest = max(candidates, key=lambda path: (path.stat().st_mtime, path.name))
            extra_args += ["--session", str(latest.resolve())]

    if resume and not no_session:
        sessions_dir = topic_sessions_dir(agent, topic_name)
        if "--session-dir" not in extra_args:
            extra_args += ["--session-dir", str(sessions_dir.resolve())]

    # Append persona context to the system prompt (kept out of chat log)
    persona = load_persona(agent_path)
    if agent_type != "kbchat" and not no_session:
        pipal_context = build_pipal_context(agent, topic_name)
        system_prompt = f"{pipal_context}\n\n---\n\n{persona}" if persona else pipal_context
    else:
        system_prompt = persona

    os.environ.pop("PIPAL_DELEGATION_RUNTIME", None)
    if agent_type != "kbchat":
        from .delegation_runtime import build_delegation_runtime

        _runtime, delegation_runtime_file = build_delegation_runtime(
            primary_name=agent.name,
            primary_path=agent_path,
            topic_name=topic_name,
            primary_llm=_session_llm_config(llm_config, extra_args),
        )
        os.environ["PIPAL_DELEGATION_RUNTIME"] = str(delegation_runtime_file.resolve())

    _run_agent_cmd(
        agent_path=agent_path,
        llm_config=llm_config,
        extra_args=extra_args,
        no_session=no_session,
        topic_name=topic_name,
        system_prompt=system_prompt,
        resume=resume,
        extensions=_extension_paths(agent_type),
    )




def run_agent_print(
    agent_path: str,
    llm_config: dict,
    prompt: str,
    no_session: bool = True,
    topic_name: str = "main",
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
        topic_name=topic_name,
        system_prompt=system_prompt,
        include_extension=True,
        extensions=_extension_paths(agent_type),
    )

    env = os.environ.copy()
    env.pop("PIPAL_DELEGATION_RUNTIME", None)
    if agent_type != "kbchat":
        from .delegation_runtime import build_delegation_runtime

        _runtime, delegation_runtime_file = build_delegation_runtime(
            primary_name=agent.name,
            primary_path=agent_path,
            topic_name=topic_name,
            primary_llm=_session_llm_config(llm_config, extra_args),
        )
        env["PIPAL_DELEGATION_RUNTIME"] = str(delegation_runtime_file.resolve())
    env["PIPAL_AGENT_DIR"] = str(agent.resolve())
    env["PIPAL_TOPIC"] = topic_name
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
