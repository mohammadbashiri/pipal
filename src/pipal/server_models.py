from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class AgentInfo:
    name: str
    path: Path


@dataclass
class SessionInfo:
    name: str
    path: Path


@dataclass
class SessionFileInfo:
    name: str
    path: Path


@dataclass
class RpcEvent:
    type: str
    data: dict[str, Any]
