from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
import os


@dataclass
class ServerSettings:
    auth_token: str | None
    cors_origins: tuple[str, ...]
    pipal_extensions_dir: Path | None
    pi_bin: str

    @staticmethod
    def load() -> "ServerSettings":
        ext_dir = os.getenv("PIPAL_EXTENSIONS_DIR")
        default_ext = Path(__file__).resolve().parent / "extensions"
        cors_origins = tuple(
            origin.strip().rstrip("/")
            for origin in os.getenv("PIPAL_CORS_ORIGINS", "").split(",")
            if origin.strip()
        )
        for origin in cors_origins:
            parsed = urlsplit(origin)
            if (
                origin == "*"
                or parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "PIPAL_CORS_ORIGINS must contain explicit http(s) origins without paths, credentials, or wildcards"
                )
        return ServerSettings(
            auth_token=os.getenv("PIPAL_AUTH_TOKEN") or os.getenv("AUTH_TOKEN"),
            cors_origins=cors_origins,
            pipal_extensions_dir=Path(ext_dir).expanduser() if ext_dir else default_ext,
            pi_bin=os.getenv("PI_BIN", "pi"),
        )
