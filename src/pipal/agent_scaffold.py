import json
import importlib.resources
from datetime import datetime
from pathlib import Path

DEFAULT_DIRS = ["sessions"]

AGENT_FILES = [
    "AGENTS.md",
    "IDENTITY.md",
    "POLICY.md",
    "USER.md",
    "MEMORY.md",
    "KB.md",
    "onboarding.md",
]

TEMPLATE_PKGS = {
    "default": "pipal.templates.default",
    "kbchat": "pipal.templates.kbchat",
}


def _load_template(filename: str, template: str) -> str:
    """Load a template file from the package's templates directory."""
    template_pkg = TEMPLATE_PKGS.get(template, TEMPLATE_PKGS["default"])
    return importlib.resources.files(template_pkg).joinpath(filename).read_text(encoding="utf-8")


def ensure_agent_scaffold(
    agent_path: str,
    name: str = "assistant",
    template: str = "default",
    kb_path: str | None = None,
    agent_type: str | None = None,
):
    p = Path(agent_path)
    p.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now().isoformat()
    for d in DEFAULT_DIRS:
        (p / d).mkdir(parents=True, exist_ok=True)

    template_pkg = TEMPLATE_PKGS.get(template, TEMPLATE_PKGS["default"])
    template_dir = importlib.resources.files(template_pkg)
    for item in template_dir.iterdir():
        if item.name in AGENT_FILES:
            fp = p / item.name
            if not fp.exists():
                content = item.read_text(encoding="utf-8")
                content = content.replace("{name}", name)
                content = content.replace("{agent_path}", str(p.resolve()))
                content = content.replace("{created_at}", created_at)
                content = content.replace("{kb_path}", kb_path or "")
                fp.write_text(content, encoding="utf-8")
        elif item.is_dir() and item.name in DEFAULT_DIRS:
            for sub in item.iterdir():
                if sub.name.endswith(".md"):
                    fp = p / item.name / sub.name
                    if not fp.exists():
                        content = sub.read_text(encoding="utf-8")
                        content = content.replace("{name}", name)
                        content = content.replace("{agent_path}", str(p.resolve()))
                        content = content.replace("{created_at}", created_at)
                        content = content.replace("{kb_path}", kb_path or "")
                        fp.write_text(content, encoding="utf-8")

    if agent_type:
        type_path = p / ".pipal_type"
        if not type_path.exists():
            type_path.write_text(f"{agent_type}\n", encoding="utf-8")

def write_llm_json(agent_path: str, provider: str, model: str):
    p = Path(agent_path) / "llm.json"
    p.write_text(json.dumps({"provider": provider, "model": model}, indent=2) + "\n", encoding="utf-8")
    return str(p)