from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass
class ServerSettings:
    auth_token: str | None
    pipal_extensions_dir: Path | None
    pi_bin: str

    @staticmethod
    def load() -> "ServerSettings":
        ext_dir = os.getenv("PIPAL_EXTENSIONS_DIR")
        default_ext = Path(__file__).resolve().parent / "extensions"
        return ServerSettings(
            auth_token=os.getenv("PIPAL_AUTH_TOKEN") or os.getenv("AUTH_TOKEN"),
            pipal_extensions_dir=Path(ext_dir).expanduser() if ext_dir else default_ext,
            pi_bin=os.getenv("PI_BIN", "pi"),
        )
