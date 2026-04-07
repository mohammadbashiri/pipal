import json, os, shutil
from pathlib import Path


def _maybe_migrate_legacy_home() -> None:
    if os.environ.get("PIPAL_HOME"):
        return
    new_base = Path.home() / ".pipal"
    old_base = Path.home() / ".pal"
    if new_base.exists() or not old_base.exists():
        return
    try:
        shutil.move(str(old_base), str(new_base))
    except OSError:
        return


def pipal_dir():
    _maybe_migrate_legacy_home()
    return Path(os.environ.get("PIPAL_HOME", Path.home() / ".pipal"))

def registry_path(): return pipal_dir() / "agents.json"

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


def _rewrite_registry_paths(reg: dict) -> bool:
    """Migrate legacy paths and convert absolute paths to relative."""
    agents = reg.get("agents", {})
    if not isinstance(agents, dict):
        return False
    old_base = Path.home() / ".pal"
    new_base = Path.home() / ".pipal"
    old_prefix = str(old_base.resolve())
    new_prefix = str(new_base.resolve())

    changed = False
    for name, entry in list(agents.items()):
        if isinstance(entry, str):
            path = entry
            entry_container = None
        elif isinstance(entry, dict):
            path = entry.get("path")
            entry_container = entry
        else:
            continue

        if not isinstance(path, str):
            continue

        entry_changed = False

        # Migrate old .pal paths
        if path.startswith(old_prefix):
            path = new_prefix + path[len(old_prefix):]
            entry_changed = True

        # Convert absolute paths to relative (portability fix)
        if Path(path).is_absolute():
            rel = _to_relative(path)
            if rel != path:
                path = rel
                entry_changed = True

        if entry_changed:
            changed = True
            if entry_container is not None:
                entry_container["path"] = path
                agents[name] = entry_container
            else:
                agents[name] = path

    return changed


def load_registry():
    migrate_registry()
    p = registry_path()
    if not p.exists(): return {"agents": {}}
    with p.open("r", encoding="utf-8") as f:
        reg = json.load(f)
    if _rewrite_registry_paths(reg):
        save_registry(reg)
    return reg

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

def _to_relative(path: str) -> str:
    """Store paths relative to pipal_dir() so the registry is portable."""
    try:
        return str(Path(path).relative_to(pipal_dir()))
    except ValueError:
        # Path is outside pipal_dir (custom location) — keep absolute
        return path

def _resolve_path(rel_or_abs: str) -> str:
    """Resolve a registry path: relative paths are anchored to pipal_dir()."""
    p = Path(rel_or_abs)
    if p.is_absolute():
        return str(p)
    return str(pipal_dir() / p)

def add_agent(name, path):
    p = registry_path()

    created = False
    if not p.exists():
        save_registry({"agents": {}})
        created = True

    reg = load_registry()
    reg.setdefault("agents", {})

    abs_path = norm_abs(path)
    reg["agents"][name] = _to_relative(abs_path)

    save_registry(reg)

    return {
        "path": abs_path,
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
        if p: out[name] = _resolve_path(p)
    return out

def get_agent(name):
    reg = load_registry()
    entry = reg.get("agents", {}).get(name)
    p = _entry_to_path(entry)
    if not p: return None
    return {"name": name, "path": _resolve_path(p)}