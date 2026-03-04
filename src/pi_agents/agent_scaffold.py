import json
from pathlib import Path

DEFAULT_FILES = {
    "identity.md": "# Identity\n\n",
    "principles.md": "# Principles\n\n",
    "strategy.md": "# Strategy\n\n",
    "reflection.md": "# Reflection\n\n",
    "memory.md": "# Memory\n\n## Preferences\n\n## Projects\n\n## People\n\n## Facts\n\n## Decisions\n\n",
    "journal.md": ""
}

DEFAULT_DIRS = ["skills", "tools", "routines", "runs"]

def ensure_agent_scaffold(agent_path: str):
    p = Path(agent_path)
    p.mkdir(parents=True, exist_ok=True)
    for d in DEFAULT_DIRS:
        (p / d).mkdir(parents=True, exist_ok=True)
    for fn, content in DEFAULT_FILES.items():
        fp = p / fn
        if not fp.exists():
            fp.write_text(content, encoding="utf-8")

def write_llm_json(agent_path: str, provider: str, model: str):
    p = Path(agent_path) / "llm.json"
    p.write_text(json.dumps({"provider": provider, "model": model}, indent=2) + "\n", encoding="utf-8")
    return str(p)