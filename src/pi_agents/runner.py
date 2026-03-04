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
]


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


def run_agent(agent_path: str, llm_config: dict, extra_args: list[str]):
    """Invoke pi with persona context, passing through any extra CLI args."""
    system_prompt = load_persona(agent_path)

    cmd = ["pi"]

    provider = llm_config.get("provider")
    model = llm_config.get("model")
    if provider:
        cmd += ["--provider", provider]
    if model:
        cmd += ["--model", model]

    if system_prompt:
        cmd += ["--system-prompt", system_prompt]

    # Pass through all remaining user args (prompts, flags, etc.)
    cmd += extra_args

    pi_bin = _find_native_pi()
    os.execv(pi_bin, cmd)
