import json, os
from pathlib import Path

def pi_dir(): return Path(os.environ.get("PI_HOME", Path.home() / ".pi"))
def registry_path(): return pi_dir() / "agents.json"

def load_registry():
    p = registry_path()
    if not p.exists(): return {"agents": {}}
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_registry(reg):
    p = registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(reg, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(p)

def init_registry():
    p = registry_path()
    if not p.exists(): save_registry({"agents": {}})
    return p

def norm_abs(path): return str(Path(path).expanduser().resolve())

def _entry_to_path(entry):
    if isinstance(entry, str): return entry
    if isinstance(entry, dict): return entry.get("path")
    return None

def add_agent(name, path):
    p = registry_path()

    # ensure pi runtime exists
    if not p.parent.exists():
        raise RuntimeError(
            "~/.pi does not exist. Install or run `pi` once before registering agents."
        )

    created = False
    if not p.exists():
        save_registry({"agents": {}})
        created = True

    reg = load_registry()
    reg.setdefault("agents", {})

    path = norm_abs(path)
    reg["agents"][name] = path

    save_registry(reg)

    return {
        "path": path,
        "registry_created": created
    }

def rm_agent(name):
    reg = load_registry()
    if name in reg.get("agents", {}):
        del reg["agents"][name]
        save_registry(reg)
        return True
    return False

def list_agents():
    reg = load_registry()
    out = {}
    for name, entry in reg.get("agents", {}).items():
        p = _entry_to_path(entry)
        if p: out[name] = str(Path(p).expanduser().resolve())
    return out

def get_agent(name):
    reg = load_registry()
    entry = reg.get("agents", {}).get(name)
    p = _entry_to_path(entry)
    if not p: return None
    p = Path(p).expanduser().resolve()
    return {"name": name, "path": str(p)}