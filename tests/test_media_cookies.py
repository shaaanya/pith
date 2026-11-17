"""Opt-in browser-cookie fetching for login-walled hosts (Instagram, TikTok), with throttling."""
import pytest
from test_media import env, url_ctx  # noqa: F401  # the fake-yt-dlp fixture and context helper

from pith.config import ConfigError, load_config
from pith.pipeline.extractors import media
from pith.pipeline.extractors.base import NeedsClarificationError

IG = "https://www.instagram.com/reel/Df0DlMHzy/"


@pytest.fixture(autouse=True)
def clean_throttle(monkeypatch):
    media._last.clear()
    sleeps, now = [], [1000.0]
    monkeypatch.setattr(media, "_clock", lambda: now[0])
    monkeypatch.setattr(media, "_sleep", lambda s: sleeps.append(s))
    return sleeps, now


def cookie_flags(calls):
    return [c[c.index("--cookies-from-browser") + 1] for c in calls if "--cookies-from-browser" in c]


def test_cookies_off_by_default(env):
    media.extract(url_ctx(env, IG))
    assert env.calls() and cookie_flags(env.calls()) == []


def test_cookies_used_only_for_listed_hosts(env):
    env.cfg.cookies_from_browser = "firefox:pith"
    media.extract(url_ctx(env, IG))
    calls = env.calls()
    assert cookie_flags(calls) == ["firefox:pith"] * len(calls)  # every yt-dlp call of the item
    assert all("--sleep-requests" in c and c[-2] == "--" for c in calls)  # URL still only after --
    before = len(calls)
    media.extract(url_ctx(env, "https://www.youtube.com/watch?v=vid123"))
    assert len(env.calls()) > before and not cookie_flags(env.calls()[before:])


def test_host_match_is_exact_not_a_suffix_trick(env):
    env.cfg.cookies_from_browser = "firefox"
    media.extract(url_ctx(env, "https://notinstagram.com/reel/x"))
    media.extract(url_ctx(env, "https://instagram.com.evil.example/reel/x"))
    assert cookie_flags(env.calls()) == []
    media.extract(url_ctx(env, "https://m.instagram.com/reel/x"))  # a real subdomain
    assert cookie_flags(env.calls())


def test_cookie_domains_is_configurable(env):
    env.cfg.cookies_from_browser = "firefox"
    env.cfg.cookie_domains = ["example.org"]
    media.extract(url_ctx(env, IG))
    assert cookie_flags(env.calls()) == []
    media.extract(url_ctx(env, "https://example.org/v"))
    assert cookie_flags(env.calls())


def test_logged_in_fetches_are_spaced_out(env, clean_throttle):
    sleeps, now = clean_throttle
    env.cfg.cookies_from_browser, env.cfg.cookie_gap_seconds = "firefox", 20
    media.extract(url_ctx(env, IG))
    assert sleeps == []  # the first fetch does not wait
    now[0] += 5
    media.extract(url_ctx(env, IG))
    assert sleeps == [15.0]  # 20s gap minus the 5s already passed
    media.extract(url_ctx(env, "https://www.youtube.com/watch?v=vid123"))
    assert sleeps == [15.0]  # other hosts are not throttled


def test_no_throttle_without_cookies(env, clean_throttle):
    sleeps, _ = clean_throttle
    media.extract(url_ctx(env, IG))
    media.extract(url_ctx(env, IG))
    assert sleeps == []


def test_login_failure_with_cookies_says_the_session_may_have_expired(env, monkeypatch):
    env.cfg.cookies_from_browser = "firefox:pith"
    monkeypatch.setenv("FAKE_YTDLP_MODE", "login")
    with pytest.raises(NeedsClarificationError) as e:
        media.extract(url_ctx(env, IG))
    msg = str(e.value)
    assert "session" in msg and "firefox:pith" in msg and "paste the transcript" in msg


def test_config_keys_and_validation(tmp_path):
    def load(toml):
        f = tmp_path / "c.toml"
        f.write_text(toml)
        return load_config(f, {"PITH_HOME": str(tmp_path / "home")})
    cfg = load("")
    assert cfg.cookies_from_browser is None and cfg.cookie_gap_seconds == 20
    assert cfg.cookie_domains == ["instagram.com", "tiktok.com"]
    cfg = load('[media]\ncookies_from_browser = "firefox:pith"\ncookie_domains = ["instagram.com"]\n'
               "cookie_gap_seconds = 45\n")
    assert (cfg.cookies_from_browser, cfg.cookie_domains, cfg.cookie_gap_seconds) == (
        "firefox:pith", ["instagram.com"], 45)
    assert load('[media]\ncookies_from_browser = ""\n').cookies_from_browser is None
    for bad in ('"--exec rm"', '"netscape"', '"firefox\\nx"', "3"):
        with pytest.raises(ConfigError):
            load(f"[media]\ncookies_from_browser = {bad}\n")
