import re
import shutil
import importlib.resources
from datetime import datetime
from pathlib import Path
from .registry import pal_dir

TEMPLATE_PKG = "pi_agents.templates.default"
TASK_TEMPLATE = "task.md"


def _slugify(title: str) -> str:
    slug = title.strip().lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    return slug.strip("-") or "task"


def task_id_from_title(title: str) -> str:
    return _slugify(title)


def _yaml_value(value: str | None) -> str:
    if value is None:
        return "null"
    return f'"{value}"'


def _load_task_template() -> str:
    return importlib.resources.files(TEMPLATE_PKG).joinpath(TASK_TEMPLATE).read_text(encoding="utf-8")


def _parse_frontmatter(content: str) -> dict:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    data = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if not line.strip() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if value in {"null", ""}:
            value = None
        elif value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        data[key.strip()] = value
    return data


def task_root_global() -> Path:
    return pal_dir() / "tasks"


def task_root_personal(agent_path: str) -> Path:
    return Path(agent_path) / "tasks"


def task_log_path(task_dir: Path) -> Path:
    return task_dir / "runs.log"


def remove_task(task_dir: Path) -> None:
    if task_dir.exists():
        shutil.rmtree(task_dir)


def create_task(
    title: str,
    agent: dict | None = None,
    schedule: str | None = None,
    assigned_to: str | None = None,
    body: str | None = None,
    status: str = "open",
) -> Path:
    task_id = _slugify(title)
    if agent:
        assigned_to = agent["name"]
    root = task_root_personal(agent["path"]) if agent else task_root_global()
    task_dir = root / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    task_file = task_dir / "task.md"
    if task_file.exists():
        raise FileExistsError(f"Task already exists: {task_file}")

    content = _load_task_template()
    content = content.replace("{task_id}", task_id)
    content = content.replace("{title}", title)
    content = content.replace("{status}", status)
    content = content.replace("{assigned_to}", _yaml_value(assigned_to))
    content = content.replace("{schedule}", _yaml_value(schedule))
    content = content.replace("{body}", body or "Describe the goal, context, and acceptance criteria here.")

    task_file.write_text(content, encoding="utf-8")
    return task_file


def list_tasks(root: Path) -> list[tuple[str, Path]]:
    if not root.exists():
        return []
    tasks = []
    for p in sorted(root.iterdir()):
        if p.is_dir() and (p / "task.md").exists():
            tasks.append((p.name, p / "task.md"))
    return tasks


def load_task(task_file: Path) -> dict:
    content = task_file.read_text(encoding="utf-8")
    data = _parse_frontmatter(content)
    task_dir = task_file.parent
    data.setdefault("id", task_dir.name)
    data["path"] = str(task_file)
    data["dir"] = str(task_dir)
    return data


def append_run_log(task_dir: Path, status: str, message: str) -> Path:
    log_path = task_log_path(task_dir)
    timestamp = datetime.now().isoformat()
    line = f"{timestamp}\t{status}\t{message}\n"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line)
    return log_path


def last_run(task_dir: Path) -> dict | None:
    log_path = task_log_path(task_dir)
    if not log_path.exists():
        return None
    lines = log_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return None
    timestamp, status, message = (lines[-1].split("\t", 2) + [""] * 3)[:3]
    return {"timestamp": timestamp, "status": status, "message": message}


def _parse_kv_pairs(payload: str) -> dict:
    pairs = {}
    for match in re.finditer(r"(\w+)\s*=\s*\"(.*?)\"", payload):
        pairs[match.group(1)] = match.group(2)
    return pairs


def parse_task_response(output: str) -> tuple[str, str]:
    out = (output or "").strip()
    if out.startswith("TASK_OK"):
        return "TASK_OK", out[len("TASK_OK"):].strip()
    if out.startswith("TASK_FAIL"):
        return "TASK_FAIL", out[len("TASK_FAIL"):].strip()
    return "TASK_FAIL", f"Unexpected output: {out[:200]}" if out else "No output"


def parse_task_message(status: str, message: str) -> dict:
    data = {"status": status, "raw": message}
    if status == "TASK_OK":
        pairs = _parse_kv_pairs(message)
        data["changes"] = pairs.get("changes")
        data["next_steps"] = pairs.get("next_steps")
    elif status == "TASK_FAIL":
        pairs = _parse_kv_pairs(message)
        data["reason"] = pairs.get("reason")
    return data
