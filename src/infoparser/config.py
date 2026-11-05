"""Configuration: TOML file plus INFOPARSER_* environment overrides."""
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(ValueError):
    """A configuration value is unusable."""


def _int(data: dict, section: str, key: str, default: int, minimum: int = 0) -> int:
    """data[section][key] as an int >= minimum (a quoted integer is coerced), else ConfigError."""
    v = data.get(section, {}).get(key, default)
    if isinstance(v, str) and v.strip().isascii() and v.strip().isdigit():
        v = int(v)
    if isinstance(v, bool) or not isinstance(v, int) or v < minimum:
        raise ConfigError(f"{section}.{key} must be an integer >= {minimum}, got {v!r}")
    return v


@dataclass
class Config:  # pylint: disable=too-many-instance-attributes  # flat settings record
    """All settings, resolved from file and environment."""

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
    digest_interval_days: int = 7
    digest_max_items: int = 20


def load_config(path: Path | None = None, env: Mapping = os.environ) -> Config:
    """Load the config file (path, else INFOPARSER_CONFIG, else none) with env overrides."""
    path = path or (Path(env["INFOPARSER_CONFIG"]) if env.get("INFOPARSER_CONFIG") else None)
    data = tomllib.loads(Path(path).expanduser().read_text(encoding="utf-8")) if path else {}
    home = Path(env.get("INFOPARSER_HOME") or data.get("home") or "~/InfoParser").expanduser()
    if not home.is_absolute():
        home = Path.home() / home
    watch = data.get("watch", {}).get("dirs", [str(home / "inbox")])
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
        max_attempts=_int(data, "limits", "max_attempts", 5, 1),
        lease_seconds=_int(data, "limits", "lease_seconds", 300, 1),
        http_bind=data.get("http", {}).get("bind", "127.0.0.1"),
        http_port=_int(data, "http", "port", 8787),
        http_token=env.get("INFOPARSER_HTTP_TOKEN") or data.get("http", {}).get("token"),
        digest_interval_days=_int(data, "digest", "interval_days", 7),
        digest_max_items=_int(data, "digest", "max_items", 20),
        max_fetch_bytes=_int(data, "limits", "max_fetch_bytes", 50_000_000, 1),
        yt_dlp_binary=env.get("INFOPARSER_YT_DLP") or data.get("media", {}).get("yt_dlp", "yt-dlp"),
        ffmpeg_binary=env.get("INFOPARSER_FFMPEG") or data.get("media", {}).get("ffmpeg", "ffmpeg"),
    )
