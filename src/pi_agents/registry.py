import json, os
from pathlib import Path

def pal_dir(): return Path(os.environ.get("PAL_HOME", Path.home() / ".pal"))
def registry_path(): return pal_dir() / "agents.json"

def legacy_registry_path():
    return Path(os.environ.get("PI_HOME", Path.home() / ".pi")) / "agents.json"

def migrate_registry():
    new_path = registry_path()
    old_path = legacy_registry_path()
    if new_path.exists() or not old_path.exists():
        return False
    new_path.parent.mkdir(parents=True, exist_ok=True)
    new_path.write_text(old_path.read_text(encoding="utf-8"), encoding="utf-8")
    return True


def load_registry():
    migrate_registry()
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
    migrate_registry()
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
    entry = reg.get("agents", {}).get(name)
    if entry is None:
        return None
    path = _entry_to_path(entry)
    del reg["agents"][name]
    save_registry(reg)
    return path

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