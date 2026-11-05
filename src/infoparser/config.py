import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    home: Path
    db_path: Path
    blobs_dir: Path
    vault_dir: Path
    watch_dirs: list[Path] = field(default_factory=list)
    backends: dict[str, dict] = field(default_factory=dict)
    tasks: dict[str, list[str]] = field(default_factory=dict)
    allow_remote: bool = False
    max_attempts: int = 5
    lease_seconds: int = 300
    max_fetch_bytes: int = 50_000_000
    yt_dlp_binary: str = "yt-dlp"
    ffmpeg_binary: str = "ffmpeg"
    http_bind: str = "127.0.0.1"
    http_port: int = 8787
    http_token: str | None = None  # explicit token required for a non-loopback bind


def load_config(path: Path | None = None, env: Mapping = os.environ) -> Config:
    path = path or (Path(env["INFOPARSER_CONFIG"]) if env.get("INFOPARSER_CONFIG") else None)
    data = tomllib.loads(Path(path).expanduser().read_text()) if path else {}
    home = Path(env.get("INFOPARSER_HOME") or data.get("home") or "~/InfoParser").expanduser()
    if not home.is_absolute():
        home = Path.home() / home
    watch = data.get("watch", {}).get("dirs", [str(home / "inbox")])
    limits = data.get("limits", {})
    tasks = {k: [v] if isinstance(v, str) else list(v) for k, v in data.get("tasks", {}).items()}
    return Config(
        home=home,
        db_path=home / "infoparser.db",
        blobs_dir=home / "blobs",
        vault_dir=home / "vault",
        watch_dirs=[Path(d).expanduser() for d in watch],
        backends={k: dict(v) for k, v in data.get("backends", {}).items()},
        tasks=tasks,
        allow_remote=bool(data.get("privacy", {}).get("allow_remote", False)),
        max_attempts=limits.get("max_attempts", 5),
        lease_seconds=limits.get("lease_seconds", 300),
        http_bind=data.get("http", {}).get("bind", "127.0.0.1"),
        http_port=int(data.get("http", {}).get("port", 8787)),
        http_token=env.get("INFOPARSER_HTTP_TOKEN") or data.get("http", {}).get("token"),
        max_fetch_bytes=limits.get("max_fetch_bytes", 50_000_000),
        yt_dlp_binary=env.get("INFOPARSER_YT_DLP") or data.get("media", {}).get("yt_dlp", "yt-dlp"),
        ffmpeg_binary=env.get("INFOPARSER_FFMPEG") or data.get("media", {}).get("ffmpeg", "ffmpeg"),
    )
