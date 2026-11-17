"""Configuration: TOML file plus PITH_* environment overrides."""
import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(ValueError):
    """A configuration value is unusable."""


def _table(data: dict, name: str) -> dict:
    """data[name] as a table ({} when absent), else ConfigError."""
    v = data.get(name, {})
    if not isinstance(v, dict):
        raise ConfigError(f"[{name}] must be a table, got {v!r}")
    return v


def _str(data: dict, section: str, key: str, default):
    """data[section][key] as a string (default when absent), else ConfigError."""
    v = _table(data, section).get(key, default)
    if v is not None and not isinstance(v, str):
        raise ConfigError(f"{section}.{key} must be a string, got {v!r}")
    return v


def _int(data: dict, section: str, key: str, default: int, minimum: int = 0) -> int:
    """data[section][key] as an int >= minimum (a quoted integer is coerced), else ConfigError."""
    v = _table(data, section).get(key, default)
    if isinstance(v, str) and v.strip().isascii() and v.strip().isdigit():
        v = int(v)
    if isinstance(v, bool) or not isinstance(v, int) or v < minimum:
        raise ConfigError(f"{section}.{key} must be an integer >= {minimum}, got {v!r}")
    return v


_BROWSER = re.compile(
    r"(?i)(brave|chrome|chromium|edge|firefox|opera|safari|vivaldi|whale)([+:][^\n\r]*)?")


def _browser(data: dict) -> str | None:
    """media.cookies_from_browser: a yt-dlp BROWSER[+KEYRING][:PROFILE] value, else ConfigError.
    The browser name must come first so the value can never be read as a command-line flag."""
    v = _str(data, "media", "cookies_from_browser", None)
    if not v:
        return None
    if not _BROWSER.fullmatch(v):
        raise ConfigError("media.cookies_from_browser must be a browser name, optionally followed "
                          f"by :PROFILE (e.g. firefox:pith), got {v!r}")
    return v


def _strs(v, what: str) -> list[str]:
    """v as a list of str (one bare string is the one-element list), else ConfigError."""
    v = [v] if isinstance(v, str) else v
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ConfigError(f"{what} must be a list of strings, got {v!r}")
    return v


def _channels(data: dict) -> dict[str, dict]:
    """[channels.<name>] tables; `enabled`, when present, must be a boolean."""
    out = {}
    for name, v in _table(data, "channels").items():
        if not isinstance(v, dict):
            raise ConfigError(f"channels.{name} must be a table, got {v!r}")
        if not isinstance(v.get("enabled", True), bool):
            raise ConfigError(f"channels.{name}.enabled must be true or false, got {v['enabled']!r}")
        out[name] = dict(v)
    return out


@dataclass
class Config:  # pylint: disable=too-many-instance-attributes  # flat settings record
    """All settings, resolved from file and environment."""

    home: Path
    db_path: Path
    blobs_dir: Path
    vault_dir: Path
    watch_dirs: list[Path] = field(default_factory=list)
    channels: dict[str, dict] = field(default_factory=dict)  # [channels.<name>] tables, raw
    backends: dict[str, dict] = field(default_factory=dict)
    tasks: dict[str, list[str]] = field(default_factory=dict)
    allow_remote: bool = False
    max_attempts: int = 5
    lease_seconds: int = 300
    max_fetch_bytes: int = 50_000_000
    yt_dlp_binary: str = "yt-dlp"
    ffmpeg_binary: str = "ffmpeg"
    cookies_from_browser: str | None = None  # opt-in: yt-dlp --cookies-from-browser value
    cookie_domains: list[str] = field(default_factory=lambda: ["instagram.com", "tiktok.com"])
    cookie_gap_seconds: int = 20  # minimum gap between logged-in fetches to one host
    http_bind: str = "127.0.0.1"
    http_port: int = 8787
    http_token: str | None = None  # explicit token required for a non-loopback bind
    digest_interval_days: int = 7
    digest_max_items: int = 20
    source: Path | None = None  # the config file this was loaded from (None: defaults only)


def _compat(env: Mapping) -> dict:
    """Accept the old INFOPARSER_* variable names; PITH_* wins when both are set."""
    return {**{"PITH_" + k[11:]: v for k, v in env.items() if k.startswith("INFOPARSER_")}, **env}


def _default_home() -> str:
    """~/Pith, or the pre-rename ~/InfoParser while that is the only one that exists."""
    old, new = Path("~/InfoParser").expanduser(), Path("~/Pith").expanduser()
    return str(old if old.exists() and not new.exists() else new)


def _find_config(env: Mapping) -> Path | None:
    """PITH_CONFIG, else <home>/config.toml when it exists (the file the dashboard edits)."""
    if env.get("PITH_CONFIG"):
        return Path(env["PITH_CONFIG"])
    found = Path(env.get("PITH_HOME") or _default_home()).expanduser() / "config.toml"
    return found if found.is_file() else None


def load_config(path: Path | None = None, env: Mapping | None = None) -> Config:
    """Load the config file (path, else PITH_CONFIG, else <home>/config.toml, else none)
    with env overrides. A <home>/config.toml found that way always lives in its own home: its
    `home` key is ignored."""
    env = _compat(os.environ if env is None else env)
    discovered = path is None and not env.get("PITH_CONFIG")
    path = path or _find_config(env)
    try:
        data = tomllib.loads(Path(path).expanduser().read_text(encoding="utf-8")) if path else {}
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise ConfigError(f"cannot read config {path}: {e}") from e
    if discovered:
        data.pop("home", None)
    if not isinstance(data.get("home", ""), str):
        raise ConfigError(f"home must be a path string, got {data['home']!r}")
    home = Path(env.get("PITH_HOME") or data.get("home") or _default_home()).expanduser()
    if not home.is_absolute():
        home = Path.home() / home
    watch = _table(data, "watch").get("dirs", [str(home / "inbox")])
    if not isinstance(watch, list):  # a bare string would be iterated per character
        raise ConfigError(f"watch.dirs must be a list of strings, got {watch!r}")
    tasks = {k: _strs(v, f"tasks.{k}") for k, v in _table(data, "tasks").items()}
    channels = _channels(data)
    for k, v in _table(data, "backends").items():
        if not isinstance(v, dict):
            raise ConfigError(f"backends.{k} must be a table, got {v!r}")
    allow_remote = _table(data, "privacy").get("allow_remote", False)
    if not isinstance(allow_remote, bool):  # bool("false") is True: fail closed instead
        raise ConfigError(f"privacy.allow_remote must be true or false, got {allow_remote!r}")
    bind = _str(data, "http", "bind", "127.0.0.1")
    return Config(
        home=home,
        db_path=home / "infoparser.db",
        blobs_dir=home / "blobs",
        vault_dir=home / "vault",
        watch_dirs=[Path(d).expanduser() for d in _strs(watch, 'watch.dirs')],
        channels=channels,
        backends={k: dict(v) for k, v in _table(data, "backends").items()},
        tasks=tasks,
        allow_remote=allow_remote,
        max_attempts=_int(data, "limits", "max_attempts", 5, 1),
        lease_seconds=_int(data, "limits", "lease_seconds", 300, 1),
        http_bind=bind,
        http_port=_int(data, "http", "port", 8787),
        http_token=env.get("PITH_HTTP_TOKEN") or _str(data, "http", "token", None),
        digest_interval_days=_int(data, "digest", "interval_days", 7),
        digest_max_items=_int(data, "digest", "max_items", 20),
        max_fetch_bytes=_int(data, "limits", "max_fetch_bytes", 50_000_000, 1),
        yt_dlp_binary=env.get("PITH_YT_DLP") or _str(data, "media", "yt_dlp", "yt-dlp"),
        ffmpeg_binary=env.get("PITH_FFMPEG") or _str(data, "media", "ffmpeg", "ffmpeg"),
        cookies_from_browser=_browser(data),
        cookie_domains=[d.lower().lstrip(".") for d in _strs(
            _table(data, "media").get("cookie_domains", ["instagram.com", "tiktok.com"]),
            "media.cookie_domains")],
        cookie_gap_seconds=_int(data, "media", "cookie_gap_seconds", 20),
        source=Path(path).expanduser() if path else None,
    )
