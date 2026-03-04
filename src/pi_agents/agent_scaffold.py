import json
import importlib.resources
from pathlib import Path

DEFAULT_DIRS = ["skills", "tools", "routines", "sessions"]

TEMPLATE_PKG = "pi_agents.templates.default"


def _load_template(filename: str) -> str:
    """Load a template file from the package's templates/default/ directory."""
    return importlib.resources.files(TEMPLATE_PKG).joinpath(filename).read_text(encoding="utf-8")


def ensure_agent_scaffold(agent_path: str, name: str = "assistant"):
    p = Path(agent_path)
    p.mkdir(parents=True, exist_ok=True)
    for d in DEFAULT_DIRS:
        (p / d).mkdir(parents=True, exist_ok=True)

    template_dir = importlib.resources.files(TEMPLATE_PKG)
    for item in template_dir.iterdir():
        if item.name.endswith(".md"):
            fp = p / item.name
            if not fp.exists():
                content = item.read_text(encoding="utf-8")
                content = content.replace("{name}", name)
                content = content.replace("{agent_path}", str(p.resolve()))
                fp.write_text(content, encoding="utf-8")
        elif item.is_dir() and item.name in DEFAULT_DIRS:
            for sub in item.iterdir():
                if sub.name.endswith(".md"):
                    fp = p / item.name / sub.name
                    if not fp.exists():
                        content = sub.read_text(encoding="utf-8")
                        content = content.replace("{name}", name)
                        content = content.replace("{agent_path}", str(p.resolve()))
                        fp.write_text(content, encoding="utf-8")

def write_llm_json(agent_path: str, provider: str, model: str):
    p = Path(agent_path) / "llm.json"
    p.write_text(json.dumps({"provider": provider, "model": model}, indent=2) + "\n", encoding="utf-8")
    return str(p)