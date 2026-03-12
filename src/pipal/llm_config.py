import json
from pathlib import Path

def _load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def _deep_merge(a, b):
    if not isinstance(a, dict) or not isinstance(b, dict): return b
    out = dict(a)
    for k, v in b.items():
        out[k] = _deep_merge(out[k], v) if k in out else v
    return out

def load_llm_config(agent_path: str):
    agent = Path(agent_path)
    base = agent / "llm.json"
    if not base.exists():
        return None
    cfg = _load_json(base)
    local = agent / "llm.local.json"
    if local.exists():
        cfg = _deep_merge(cfg, _load_json(local))
    return cfg